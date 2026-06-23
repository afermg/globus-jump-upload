---
name: globus-jump-upload
description: >-
  Operational playbook for uploading data to a Globus Connect Server v5
  collection from a machine where Globus Connect Personal's relay protocol
  (port 2223) is blocked. Use when the user wants to push data to a Globus
  collection and the standard `globus transfer` path is unavailable, or
  when diagnosing GCP setup hangs.
allowed-tools: Bash(*)
---

# Globus upload: diagnosing relay blocks, working around with HTTPS

The "standard" Globus upload story is: install Globus Connect Personal (GCP)
locally, register it as an endpoint with `globus gcp create mapped`, run
`globusconnectpersonal -setup KEY`, then `globus transfer src_endpoint:/path
dst_collection:/path --recursive`. This depends on the GCP relay protocol
(SSH to `relay.globusonline.org:2223`).

That story breaks when outbound TCP `relay.globusonline.org:2223` is blocked
by a firewall that lets the TCP handshake complete but drops the bytes the
server sends back. `globusconnectpersonal -setup KEY` then hangs at "starting
relaytool setup" indefinitely.

This skill documents:
1. How to recognise the failure.
2. How to bypass it via the destination collection's HTTPS endpoint.
3. The gotchas of the HTTPS upload protocol.

## 1. Diagnose

```bash
# (a) Can the relay even take a TCP connection?
timeout 5 bash -c 'exec 3<>/dev/tcp/relay.globusonline.org/2223; echo connected'
# exit 0 → TCP handshake works (necessary but not sufficient).

# (b) Does the SSH banner come back? This is the real test.
timeout 8 bash -c 'exec 3<>/dev/tcp/relay.globusonline.org/2223; head -c 64 <&3 | od -c | head -2'
# 64 bytes of banner within 8s → relay is reachable; GCP setup will work.
# Hang + exit 124 → relay is blackholed; GCP setup will hang. Skip to (2).

# (c) Sanity-check that *some* SSH host works (rules out a broken ssh binary).
timeout 5 ssh -v -p 22 -o BatchMode=yes git@github.com 2>&1 | grep -E 'Remote protocol'
# Should print the remote version immediately.
```

If (a) is fine, (b) hangs, and (c) works, you have the blackhole. Don't
chase ssh keys, NixOS patchelf, or GCP install bugs. Skip to the HTTPS
workaround.

## 2. HTTPS upload workaround

GCS v5 collections expose a per-collection HTTPS URL that is independent
of the GCP relay. You need two things:

```bash
# Auth (first time only; needs to consent to the collection's GCS):
globus login
globus login --gcs <MAPPED_COLLECTION_ID> --no-local-server

# Discover the collection's HTTPS URL and write policy:
globus gcs collection show <COLLECTION_ID>
# Look at:
#   HTTPS URL:                https://g-XXXXX.YYYYY.ZZZZZ.data.globus.org
#   Disable Anonymous Writes: False     ← anonymous PUTs are allowed
#   Mapped Collection ID:     <UUID>
```

`Disable Anonymous Writes: False` means `curl -X PUT --data-binary @file URL/path`
works without any token. Token-required collections take an
`Authorization: Bearer <token>` header.

### Protocol gotchas

These are the non-obvious bits of the GCS v5 HTTPS API:

- **`PUT /a/b/file` returns 404 if `/a/b/` does not exist.** It does not
  auto-create parents.
- **Create a directory with `PUT /a/b/` (trailing slash).** It returns 200
  with no body. This is idempotent — re-PUT'ing an existing dir is fine.
- **`MKCOL` and `POST` return `307`** redirects to the API host. They do
  not create directories. Use `PUT` with trailing slash instead.
- **`HEAD /a/b/file`** returns 200 + Content-Length if the file exists.
  Use this for resumable uploads — skip files whose remote size matches
  local.
- **`DELETE /a/b/file`** works for files and empty dirs.
- **Port 443.** The HTTPS URL (and TLSFTP) are on 443, so they punch
  through any firewall that allows HTTPS even when the relay on 2223
  doesn't.

### Operational pattern for big trees

For a directory tree with many small files (e.g. a zarr store with
millions of `.zarray`/`.zattrs`/chunk files), the working recipe is:

1. Enumerate dirs and files locally (`os.walk` / `find`).
2. `PUT /path/` for every subdirectory, in parallel.
3. `PUT /path/file` for every file, in parallel. HEAD first to skip
   already-uploaded files for resumability.
4. Retry transient failures with exponential backoff (429/5xx).
5. 64–128 concurrent requests saturates a typical GCS v5 frontend; going
   higher buys little and risks 429s.

`upload_https.py` in this repo implements all of this. Invoke as:

```bash
python upload_https.py SRC_DIR https://g-XXX.../path/dst
# add --workers N, --no-skip-existing, --token TOKEN as needed
```

For long runs, wrap in `screen` so the transfer survives ssh disconnects.

## 3. Sanity checks before kicking off a multi-hour upload

- **Probe one file end-to-end first** with `curl -X PUT --data-binary @small_file URL/test`
  and a `GET` to confirm it round-trips. Cleanup with `DELETE`.
- **Probe a nested PUT** to confirm whether parents auto-create on the
  particular collection (most don't; some patched collections might).
- **Count the upload set.** `find SRC -type f | wc -l` for files,
  `du -sb SRC` for bytes. Estimate time at ~50–200 files/s and your
  observed PUT throughput.
- **Run a small chunk first** (e.g. one subdir of the zarr) to validate
  the directory layout before committing to the full multi-hour run.

## 4. What not to bother with when the relay is blocked

- Reinstalling GCP, rebuilding the Nix derivation, or rerunning
  `-setup` with a fresh key. The hang is in `relaytool`'s ssh, not the
  install.
- Tweaking `~/.ssh/config` or `~/.globusonline/lta/relay-known-hosts.txt`.
  The relay never sends a banner, so client-side keys/algos are irrelevant.
- Trying `globus endpoint create` — that command has been removed from
  the CLI; use `globus gcp create mapped` instead. But it doesn't help
  here either, because the bottleneck is the relay, not the endpoint
  registration.
- Asking for a "different relay host". Globus's relay infrastructure is
  centralised; there is no alternate hostname to try.

## 5. Open the auth URL from a headless box

If `globus login --no-local-server` prints an auth URL and you're on a
headless server, use the emacs-pair `browse-url.sh --host HOST URL`
helper to ask another machine's Emacs (with `M-x server-start`) to open
the URL in its browser. Or just paste the URL into a browser on any
machine — the code paste-back is what really needs to happen on the
headless server.
