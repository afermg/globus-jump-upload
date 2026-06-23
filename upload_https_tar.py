"""Stream-upload a directory as a single uncompressed tar to a Globus
HTTPS endpoint. Used when the collection forbids anonymous mkdir but
still accepts file PUTs at existing paths.

The exact uncompressed tar size is precomputed from `os.walk` and
`stat`, so the PUT can set a real Content-Length (the GCS Apache
frontend rejects chunked transfer encoding for PUT).

Usage:
    python upload_https_tar.py SRC_DIR DST_HTTPS_URL [--token TOKEN]

Example:
    python upload_https_tar.py \\
        /work/datasets/jump_lite/.../jpegxl_lossy_mq.zarr \\
        https://g-c8e504.dd271.03c0.data.globus.org/images/JUMP-lite/jpegxl_lossy_mq.tar
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests


def predict_tar_size(src: Path) -> int:
    """Compute the exact size of `tar -b1 -cf - SRC.name` from `os.walk`.

    Layout per the POSIX ustar format used by GNU tar by default:
      - 1 × 512-byte header per entry (file or directory).
      - File content rounded up to a multiple of 512.
      - 2 × 512 trailing zero blocks.
      - With `-b1` (1-block records, no extra padding to 10240),
        the result is the byte stream above with no further padding.

    Filenames over 100 chars would require a `GNU LongName` extension
    (extra header + name bytes). The JUMP-lite layout keeps all names
    under 100 chars, so we don't model that case.
    """
    total = 512  # top-level dir entry (the SRC dir itself)
    for root, dirnames, filenames in os.walk(src):
        # subdirs (skip the top once, which we already counted)
        if Path(root) != src:
            total += 512
        for d in dirnames:
            # nothing here — descended-into dirs handled by their own iteration
            pass
        for f in filenames:
            sz = os.path.getsize(os.path.join(root, f))
            total += 512 + ((sz + 511) // 512) * 512
    total += 1024  # end-of-archive
    return total


class CountingReader:
    """Wrap a file-like stream and count bytes read for progress."""

    def __init__(self, stream, total: int, log_every: float = 30.0):
        self.stream = stream
        self.total = total
        self.read_bytes = 0
        self.t_start = time.time()
        self.t_last_log = self.t_start
        self.log_every = log_every

    def read(self, n: int = -1) -> bytes:
        chunk = self.stream.read(n)
        if chunk:
            self.read_bytes += len(chunk)
            now = time.time()
            if now - self.t_last_log >= self.log_every:
                elapsed = now - self.t_start
                rate = self.read_bytes / elapsed if elapsed else 0
                eta = (self.total - self.read_bytes) / rate if rate else float("inf")
                pct = 100 * self.read_bytes / self.total if self.total else 0
                print(
                    f"  [{elapsed:6.0f}s] {self.read_bytes / 1e9:7.2f}/{self.total / 1e9:.2f} GB "
                    f"({pct:5.1f}%, {rate / 1e6:.1f} MB/s, eta {eta / 60:.0f}m)",
                    flush=True,
                )
                self.t_last_log = now
        return chunk


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("src", type=Path, help="Local source directory to tar")
    ap.add_argument("dst", help="Destination HTTPS URL of the tar file")
    ap.add_argument("--token", default=os.environ.get("GLOBUS_HTTPS_TOKEN"))
    args = ap.parse_args()

    src = args.src.resolve()
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 2

    print(f"predicting tar size for {src} ...", flush=True)
    size = predict_tar_size(src)
    print(f"  size: {size:,} bytes ({size / 1e9:.2f} GB)", flush=True)

    parent = src.parent
    name = src.name

    print(f"spawning: tar -b1 -cf - -C {parent} {name}", flush=True)
    tar = subprocess.Popen(
        ["tar", "-b1", "-cf", "-", "-C", str(parent), name],
        stdout=subprocess.PIPE,
        bufsize=1 << 20,
    )

    headers = {
        "Content-Length": str(size),
        "Content-Type": "application/x-tar",
    }
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    body = CountingReader(tar.stdout, size)

    t0 = time.time()
    print(f"PUT {args.dst}", flush=True)
    try:
        r = requests.put(args.dst, data=body, headers=headers, stream=True)
    except Exception:
        tar.kill()
        raise
    tar.wait()
    elapsed = time.time() - t0
    bytes_sent = body.read_bytes
    print(
        f"\ndone in {elapsed / 60:.1f}m: HTTP {r.status_code}, "
        f"{bytes_sent / 1e9:.2f} GB sent "
        f"({bytes_sent / 1e6 / elapsed:.1f} MB/s avg)",
        flush=True,
    )
    if r.status_code not in (200, 201, 204):
        print(f"FAIL: body = {r.text[:500]}", file=sys.stderr, flush=True)
        return 1
    if bytes_sent != size:
        print(
            f"WARN: predicted {size} bytes, sent {bytes_sent} "
            f"(tar exit {tar.returncode})",
            file=sys.stderr,
            flush=True,
        )
    if tar.returncode != 0:
        print(f"tar exited with {tar.returncode}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
