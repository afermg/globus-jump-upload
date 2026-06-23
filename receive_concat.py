"""Reassemble a .tar uploaded as .partNNNNN chunks by upload_https_tar_parts.py.

Expects the files (manifest + parts) sitting in a directory.

Usage:
    python receive_concat.py SRC_DIR_WITH_PARTS [--out OUTFILE] [--keep-parts]
        SRC_DIR is the directory holding {name}.tar.partNNNNN and {name}.tar.manifest.
        If --out is omitted, the script writes to {name}.tar next to the manifest.

To then untar:
    tar -xf {name}.tar
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep-parts", action="store_true", help="Do not delete parts after concatenation")
    args = ap.parse_args()

    src = args.src_dir.resolve()
    manifests = list(src.glob("*.tar.manifest"))
    if len(manifests) != 1:
        print(f"error: expected exactly one *.tar.manifest in {src}, found {len(manifests)}", file=sys.stderr)
        return 2
    manifest = json.loads(manifests[0].read_text())
    name = manifest["name"]
    n_chunks = manifest["n_chunks"]
    total = manifest["total_bytes"]

    out = args.out or (src / f"{name}.tar")
    print(f"writing {n_chunks} parts -> {out} (expected {total:,} bytes)")
    written = 0
    with open(out, "wb") as o:
        for idx in range(n_chunks):
            part = src / f"{name}.tar.part{idx:05d}"
            if not part.exists():
                print(f"error: missing {part}", file=sys.stderr)
                return 2
            with open(part, "rb") as p:
                while True:
                    buf = p.read(1 << 22)
                    if not buf:
                        break
                    o.write(buf)
                    written += len(buf)
    if written != total:
        print(f"WARN: wrote {written} bytes, manifest expected {total}", file=sys.stderr)
        return 1
    print(f"OK: {written:,} bytes")

    if not args.keep_parts:
        for idx in range(n_chunks):
            (src / f"{name}.tar.part{idx:05d}").unlink(missing_ok=True)
        manifests[0].unlink(missing_ok=True)
        print(f"cleaned up parts + manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
