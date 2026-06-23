# globus-jump-upload

Push large directory trees (e.g. zarr stores) to a Globus Connect Server v5
collection over its **HTTPS endpoint** instead of the relay-based Globus
transfer path. Useful when:

- The GCP relay (`relay.globusonline.org:2223`) is firewalled.
- The collection permits anonymous (or token-authenticated) HTTPS writes.
- Directory creation is locked down on the collection — so the data must
  ship as one or more files into a pre-existing folder.

## What's in here

| File | Purpose |
|------|---------|
| `upload_https_tar_parts.py` | Streams `tar -b1 -cf -` of a source dir and uploads it as N parallel `.tar.partNNNNN` chunks plus a `.tar.manifest`. |
| `receive_concat.py` | On the receiver side: reads the manifest, concatenates parts in order, optionally cleans up. |
| `flake.nix` / `flake.lock` | Reproducible env (`nix develop`) with `globus-cli`, `globusconnectpersonal`, and a Python with `requests` for the uploader. |
| `skills/globus-jump-upload/SKILL.md` | Operational playbook (diagnostic recipe, protocol gotchas, dual-API path semantics) for future agents. |

## Quick start

```bash
# Inside the repo:
nix develop

# Upload one source dir as parallel tar parts to a destination URL.
python upload_https_tar_parts.py \
  /path/to/source_dir \
  https://g-XXXXX.YYYYY.data.globus.org/path/to/dest_folder \
  --chunk-size $((64*1024*1024)) --workers 32

# On the receive side, after pulling the parts:
python receive_concat.py /local/dir/with/parts
tar -xf source_dir.tar
```

The destination folder must already exist on the collection. The script
PUTs `{name}.tar.part00000`, `…part00001`, … and a `{name}.tar.manifest`
into it.

## Why split the tar — the speedup that mattered

This collection's HTTPS frontend rate-limits a single sustained PUT to
about **2 MB/s**, regardless of identity. Splitting the same tar into
64 MiB parts uploaded over 32 parallel TCP connections moves the bottleneck
from per-stream cap to aggregate bandwidth.

Measured on the JUMP-lite MQ dataset (117 GB):

| Strategy | Throughput | Wall time (mq) | Wall time (mq + hq + d20) |
|----------|-----------|----------------|---------------------------|
| Single tar PUT (`-T -` with Content-Length) | ~2 MB/s | ~15 h | ~58 h |
| 32 × 64 MiB parts in parallel | ~50 MB/s | ~40 min | ~3 h |

Roughly a **20× speedup** at no cost beyond having to concatenate the
parts on the receiving side.

## Reassembling on the receiver

Two equivalent ways:

```bash
# Verifying (preferred — uses the manifest):
python receive_concat.py /dir/with/parts
tar -xf jpegxl_lossy_mq.zarr.tar

# Bare shell (skips manifest verification):
cat MQ/jpegxl_lossy_mq.zarr.tar.part?????  > mq.tar
tar -xf mq.tar
```

`receive_concat.py` reads the `.tar.manifest` JSON (total bytes, chunk
count) and refuses to write the wrong byte count.

## Known issue: the relay path doesn't work here

`globusconnectpersonal -setup KEY` hangs at "starting relaytool setup" on
networks where `relay.globusonline.org:2223` accepts TCP but drops the
server's SSH banner. The HTTPS path in this repo is the workaround. The
diagnostic recipe + protocol gotchas are written up in
`skills/globus-jump-upload/SKILL.md`.
