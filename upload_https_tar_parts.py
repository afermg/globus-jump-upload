"""Stream-tar a directory and upload it as N fixed-size .partNNNN files
in parallel to a Globus HTTPS endpoint.

Why this exists: the GCS Apache frontend rejects chunked transfer
encoding for PUT, so streamed uploads need a known Content-Length. A
single sustained PUT also hits a per-stream rate cap (~2 MB/s observed
to this collection). Splitting the tar into fixed-size chunks lets us
fan out across many TCP connections in parallel for much higher
aggregate throughput.

Output layout in the destination directory:
    {name}.tar.partNNNNN   (one per chunk, fixed CHUNK_SIZE except last)
    {name}.tar.manifest    (JSON: total size, chunk count, per-chunk sizes)

Receiver reconstructs with `receive_concat.py`:
    cat *.partNNNNN > {name}.tar; tar -xf {name}.tar
or use the manifest for verification.

Usage:
    python upload_https_tar_parts.py SRC_DIR DST_HTTPS_DIR_URL [options]

Example:
    python upload_https_tar_parts.py \\
        /work/.../jpegxl_lossy_mq.zarr \\
        https://g-c8e504.dd271.03c0.data.globus.org/images/JUMP-lite/images/MQ \\
        --chunk-size 67108864 --workers 32
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def predict_tar_size(src: Path) -> int:
    """Exact size of `tar -b1 -cf - src.name` from os.walk + stat.

    POSIX ustar: 512-byte header per entry, file data rounded up to
    512, 1024-byte trailer. `-b1` disables block padding. Filenames
    over 100 chars need extensions; JUMP-lite stays under that limit.
    """
    total = 512  # top-level dir header
    for root, dirnames, filenames in os.walk(src):
        if Path(root) != src:
            total += 512
        for f in filenames:
            sz = os.path.getsize(os.path.join(root, f))
            total += 512 + ((sz + 511) // 512) * 512
    total += 1024  # end-of-archive
    return total


def make_session(workers: int, max_retries: int, token: str | None) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["PUT", "HEAD", "GET", "DELETE"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=workers * 2,
        pool_maxsize=workers * 2,
        max_retries=retry,
    )
    s.mount("https://", adapter)
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def upload_part(
    session: requests.Session,
    base_url: str,
    idx: int,
    data: bytes,
    skip_existing: bool,
) -> tuple[int, str, int]:
    url = f"{base_url}.tar.part{idx:05d}"
    if skip_existing:
        h = session.head(url)
        if h.status_code == 200:
            try:
                remote = int(h.headers.get("content-length", "-1"))
            except ValueError:
                remote = -1
            if remote == len(data):
                return idx, "skip", len(data)
    headers = {
        "Content-Length": str(len(data)),
        "Content-Type": "application/octet-stream",
    }
    r = session.put(url, data=data, headers=headers)
    if r.status_code in (200, 201, 204):
        return idx, "ok", len(data)
    return idx, f"FAIL {r.status_code}", len(data)


def stream_chunks(stdout, chunk_size: int):
    """Yield (idx, bytes) chunks of up to chunk_size, until EOF."""
    idx = 0
    while True:
        buf = bytearray()
        while len(buf) < chunk_size:
            need = chunk_size - len(buf)
            piece = stdout.read(min(1 << 20, need))
            if not piece:
                break
            buf.extend(piece)
        if not buf:
            return
        yield idx, bytes(buf)
        idx += 1


def run(args) -> int:
    src = args.src.resolve()
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 2

    parent = src.parent
    name = src.name
    base_url = args.dst.rstrip("/") + "/" + name

    print(f"predicting tar size for {src} ...", flush=True)
    total = predict_tar_size(src)
    n_chunks = (total + args.chunk_size - 1) // args.chunk_size
    print(
        f"  total: {total:,} bytes ({total / 1e9:.2f} GB), "
        f"{n_chunks} parts of {args.chunk_size / 1e6:.0f} MB each",
        flush=True,
    )
    print(f"  parts: {base_url}.tar.partNNNNN", flush=True)

    session = make_session(args.workers, args.max_retries, args.token)

    # Upload manifest first so receiver can find total + chunk count
    manifest = {
        "source_dir": str(src),
        "name": name,
        "total_bytes": total,
        "chunk_size": args.chunk_size,
        "n_chunks": n_chunks,
    }
    manifest_url = f"{base_url}.tar.manifest"
    manifest_body = json.dumps(manifest, indent=2).encode()
    r = session.put(
        manifest_url,
        data=manifest_body,
        headers={"Content-Length": str(len(manifest_body)), "Content-Type": "application/json"},
    )
    print(f"manifest -> {r.status_code} ({manifest_url})", flush=True)

    tar = subprocess.Popen(
        ["tar", "-b1", "-cf", "-", "-C", str(parent), name],
        stdout=subprocess.PIPE,
        bufsize=1 << 22,
    )

    t_start = time.time()
    sent_bytes = 0
    n_ok = n_skip = n_fail = 0
    max_inflight = args.workers + 2

    def task(idx, data):
        return upload_part(session, base_url, idx, data, args.skip_existing)

    def process(f):
        nonlocal sent_bytes, n_ok, n_skip, n_fail
        i, status, sz = f.result()
        if status == "ok":
            n_ok += 1
            sent_bytes += sz
        elif status == "skip":
            n_skip += 1
            sent_bytes += sz
        else:
            n_fail += 1
            if n_fail <= 20:
                print(f"  part {i:05d} {status}", file=sys.stderr, flush=True)
        done_chunks = n_ok + n_skip + n_fail
        if done_chunks % max(1, n_chunks // 50) == 0 or done_chunks == n_chunks:
            elapsed = time.time() - t_start
            rate = sent_bytes / elapsed if elapsed else 0
            eta = (total - sent_bytes) / rate if rate else float("inf")
            print(
                f"  [{elapsed:6.0f}s] {done_chunks}/{n_chunks} parts "
                f"({sent_bytes / 1e9:6.2f}/{total / 1e9:.2f} GB, "
                f"{rate / 1e6:5.1f} MB/s, eta {eta / 60:.0f}m, "
                f"ok={n_ok} skip={n_skip} fail={n_fail})",
                flush=True,
            )

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        pending: set = set()
        for idx, data in stream_chunks(tar.stdout, args.chunk_size):
            while len(pending) >= max_inflight:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for f in done:
                    process(f)
            pending.add(ex.submit(task, idx, data))
        # drain remaining
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                process(f)

    tar.wait()
    elapsed = time.time() - t_start
    print(
        f"\ndone in {elapsed / 60:.1f}m: {n_ok} ok, {n_skip} skipped, {n_fail} failed; "
        f"{sent_bytes / 1e9:.2f} GB sent "
        f"({sent_bytes / 1e6 / elapsed:.1f} MB/s avg)",
        flush=True,
    )
    if tar.returncode != 0:
        print(f"WARN: tar exited with {tar.returncode}", file=sys.stderr, flush=True)
    if n_fail or tar.returncode != 0:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("src", type=Path, help="Local source directory")
    ap.add_argument("dst", help="Destination HTTPS dir URL (parent of the .tar.partNNN files)")
    ap.add_argument("--chunk-size", type=int, default=64 * 1024 * 1024, help="Bytes per part (default 64 MiB)")
    ap.add_argument("--workers", type=int, default=32, help="Concurrent uploads (default 32)")
    ap.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Re-upload parts even if HEAD shows matching size",
    )
    ap.add_argument("--token", default=os.environ.get("GLOBUS_HTTPS_TOKEN"))
    ap.add_argument("--max-retries", type=int, default=5)
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
