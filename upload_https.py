"""Parallel HTTPS uploader for a Globus Connect Server v5 collection.

Workaround for environments where Globus Connect Personal's relay protocol
(SSH on port 2223 to relay.globusonline.org) is firewalled. The destination
collection's HTTPS URL works through any firewall that allows HTTPS to
*.data.globus.org.

Usage:
    python upload_https.py SRC_DIR DST_HTTPS_URL [options]

Example:
    python upload_https.py \\
        /work/datasets/jump_lite/.../jpegxl_lossy_mq.zarr \\
        https://g-c8e504.dd271.03c0.data.globus.org/images/JUMP-lite/jpegxl_lossy_mq.zarr

Notes on the protocol the script targets (GCS v5 HTTPS endpoint):
  - PUT /path           uploads a file. 404 if the parent dir does not exist.
  - PUT /path/          (trailing slash) creates a directory.
  - HEAD /path          returns 200 + Content-Length if the file exists.
  - DELETE /path        removes a file or empty dir.
  - 307 from MKCOL/POST is a redirect to the API host, not a way to mkdir.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class Config:
    src: Path
    dst: str
    workers: int
    skip_existing: bool
    token: str | None
    max_retries: int


def make_session(workers: int, max_retries: int, token: str | None) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=workers * 2,
        pool_maxsize=workers * 2,
        max_retries=retry,
    )
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def enumerate_tree(src: Path) -> tuple[list[Path], list[Path]]:
    """Walk src and return (dirs, files), both as paths relative to src."""
    dirs: list[Path] = []
    files: list[Path] = []
    for root, dirnames, filenames in os.walk(src):
        rroot = Path(root).relative_to(src)
        if str(rroot) != ".":
            dirs.append(rroot)
        for fn in filenames:
            files.append(rroot / fn)
    return dirs, files


def mkdir(session: requests.Session, base: str, rel: Path) -> tuple[Path, int]:
    url = f"{base.rstrip('/')}/{str(rel).replace(os.sep, '/')}/"
    r = session.put(url, data=b"")
    return rel, r.status_code


def upload_one(
    session: requests.Session,
    base: str,
    src: Path,
    rel: Path,
    skip_existing: bool,
) -> tuple[Path, str]:
    local = src / rel
    size = local.stat().st_size
    url = f"{base.rstrip('/')}/{str(rel).replace(os.sep, '/')}"
    if skip_existing:
        h = session.head(url)
        if h.status_code == 200:
            try:
                remote_size = int(h.headers.get("content-length", "-1"))
            except ValueError:
                remote_size = -1
            if remote_size == size:
                return rel, "skip"
    with open(local, "rb") as f:
        r = session.put(url, data=f)
    if r.status_code in (200, 201, 204):
        return rel, f"ok {r.status_code}"
    return rel, f"FAIL {r.status_code}"


def run(cfg: Config) -> int:
    if not cfg.src.is_dir():
        print(f"error: source dir does not exist: {cfg.src}", file=sys.stderr)
        return 2

    session = make_session(cfg.workers, cfg.max_retries, cfg.token)

    print(f"enumerating {cfg.src} ...", flush=True)
    dirs, files = enumerate_tree(cfg.src)
    total_bytes = sum((cfg.src / f).stat().st_size for f in files)
    print(
        f"  {len(dirs):,} dirs, {len(files):,} files, "
        f"{total_bytes / 1e9:.1f} GB",
        flush=True,
    )

    # Create the root path itself first, in case the destination dir
    # for the upload doesn't exist yet.
    root_url = cfg.dst.rstrip("/") + "/"
    r = session.put(root_url, data=b"")
    print(f"mkdir root  -> {r.status_code}", flush=True)

    # Create all subdirectories in parallel. Sort so parents are created
    # before children — GCS doesn't seem to need this but it's cheap and
    # avoids surprises.
    dirs.sort(key=lambda p: len(p.parts))
    print(f"mkdir {len(dirs):,} subdirs (workers={cfg.workers}) ...", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
        futs = [ex.submit(mkdir, session, cfg.dst, d) for d in dirs]
        done = 0
        bad = 0
        for fut in as_completed(futs):
            rel, code = fut.result()
            done += 1
            if code not in (200, 201, 204):
                bad += 1
                if bad <= 10:
                    print(f"  mkdir FAIL {code} {rel}", file=sys.stderr, flush=True)
            if done % 5000 == 0:
                print(
                    f"  {done:,}/{len(dirs):,} dirs "
                    f"({done / (time.time() - t0):.0f}/s, {bad} fails)",
                    flush=True,
                )
    print(f"mkdir done in {time.time() - t0:.0f}s, {bad} failures", flush=True)

    # Upload files in parallel.
    print(f"uploading {len(files):,} files (workers={cfg.workers}) ...", flush=True)
    t0 = time.time()
    bytes_done = 0
    n_ok = n_skip = n_fail = 0
    with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
        futs = {
            ex.submit(upload_one, session, cfg.dst, cfg.src, f, cfg.skip_existing): f
            for f in files
        }
        for fut in as_completed(futs):
            rel, status = fut.result()
            local = cfg.src / rel
            sz = local.stat().st_size
            if status.startswith("ok"):
                n_ok += 1
                bytes_done += sz
            elif status == "skip":
                n_skip += 1
                bytes_done += sz
            else:
                n_fail += 1
                if n_fail <= 20:
                    print(f"  PUT FAIL {status} {rel}", file=sys.stderr, flush=True)
            done = n_ok + n_skip + n_fail
            if done % 5000 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 0
                mb_s = bytes_done / 1e6 / elapsed if elapsed else 0
                eta = (len(files) - done) / rate if rate else float("inf")
                print(
                    f"  {done:,}/{len(files):,} "
                    f"({rate:.0f} files/s, {mb_s:.1f} MB/s, "
                    f"eta {eta / 60:.0f}m, ok={n_ok:,} skip={n_skip:,} fail={n_fail:,})",
                    flush=True,
                )
    elapsed = time.time() - t0
    print(
        f"\nuploaded {n_ok:,} files, skipped {n_skip:,}, failed {n_fail:,} "
        f"in {elapsed / 60:.1f}m "
        f"({bytes_done / 1e9:.1f} GB, avg {bytes_done / 1e6 / elapsed:.1f} MB/s)",
        flush=True,
    )
    return 0 if n_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("src", type=Path, help="Local source directory")
    ap.add_argument(
        "dst",
        help="Destination HTTPS URL, e.g. https://g-XXX.YYY.data.globus.org/path/to/dir",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=64,
        help="Concurrent uploads (default 64; HTTPS endpoint scales well past 100)",
    )
    ap.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-upload files even if HEAD shows matching size (default: skip)",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("GLOBUS_HTTPS_TOKEN"),
        help="Bearer token for non-anonymous collections (or set GLOBUS_HTTPS_TOKEN)",
    )
    ap.add_argument("--max-retries", type=int, default=5)
    args = ap.parse_args()

    return run(
        Config(
            src=args.src.resolve(),
            dst=args.dst,
            workers=args.workers,
            skip_existing=args.skip_existing,
            token=args.token,
            max_retries=args.max_retries,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
