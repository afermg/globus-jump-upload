# Globus JUMP-lite Upload Instructions

This repository contains instructions and scripts for uploading JUMP-lite data to the Broad Globus collection.

## Destination Collection

- **Collection ID**: `20317ea0-5bda-471d-aba2-191c9028f1d8`
- **Path**: `/images/JUMP-lite/`
- **Web Interface**: https://app.globus.org/file-manager?origin_id=20317ea0-5bda-471d-aba2-191c9028f1d8&origin_path=%2Fimages%2FJUMP-lite%2F

## Prerequisites

1. Install Globus CLI:
   ```bash
   pip install globus-cli
   # or with uv:
   uv pip install globus-cli
   ```

2. Authenticate with Globus:
   ```bash
   globus login
   ```

## Option 1: Upload from Local Machine (Globus Connect Personal)

### Setup

1. Download and install Globus Connect Personal:
   - Linux: https://www.globus.org/globus-connect-personal
   - Follow installation instructions for your OS

2. Start Globus Connect Personal and note your endpoint ID:
   ```bash
   globus endpoint search --filter-scope my-endpoints
   ```

### Upload Data

```bash
# Replace YOUR_LOCAL_ENDPOINT_ID with your Globus Connect Personal endpoint
globus transfer YOUR_LOCAL_ENDPOINT_ID:/home/amunoz/datasets/alan/jump_lite/ \
  20317ea0-5bda-471d-aba2-191c9028f1d8:/images/JUMP-lite/ \
  --recursive \
  --label "JUMP-lite dataset upload"
```

## Option 2: Upload from Shared/Institutional Endpoint (e.g., Broad or oppy)

### Find Your Endpoint

Search for your institutional endpoint:
```bash
# Example: search for Broad endpoints
globus endpoint search "Broad"

# List all accessible endpoints
globus endpoint search --filter-scope my-endpoints
```

### Upload Data

Once you've identified your source endpoint ID:

```bash
globus transfer SOURCE_ENDPOINT_ID:/path/to/jump_lite/ \
  20317ea0-5bda-471d-aba2-191c9028f1d8:/images/JUMP-lite/ \
  --recursive \
  --label "JUMP-lite dataset upload from oppy"
```

## Monitoring Transfers

Check transfer status:
```bash
# List recent transfers
globus task list

# Get details of a specific transfer
globus task show TASK_ID

# Monitor transfer in real-time
globus task wait TASK_ID --polling-interval 10
```

## Example Upload Script

See `upload_to_globus.sh` for a complete example script.

## Data Location

**Source data (oppy)**: `/home/amunoz/datasets/alan/jump_lite/`

**Destination**: Broad Globus Collection at `/images/JUMP-lite/`

## Troubleshooting

### Authentication Issues
```bash
# Re-authenticate if needed
globus logout
globus login
```

### Permission Issues
If you get permission errors, contact Jess or the collection's admin to ensure you have write access.

### Large Transfers
For very large datasets, Globus transfers are:
- Fault-tolerant (auto-retry)
- Can resume after interruption
- Run in the background (you can close terminal)
- Optimized for high-throughput

## Known issue: relay handshake blocked by firewall (and the HTTPS workaround)

`globusconnectpersonal -setup KEY` will hang indefinitely on networks that
silently drop incoming bytes from `relay.globusonline.org:2223` after the
TCP handshake. Symptom:

- TCP connect to `relay.globusonline.org:2223` succeeds.
- The client sends its `SSH-2.0-OpenSSH_*` version banner.
- The server never sends back its `Remote protocol version` banner.
  `ssh -v ...` shows the connection established, prints the local
  version string, and then hangs.

We saw this on both `oppy` and `moby` (Broad / EBI networks). It is not
a Nix or GCP install bug — it's a network-layer blackhole. Diagnose with:

```bash
# Confirm TCP handshake works but no banner arrives:
timeout 8 bash -c 'exec 3<>/dev/tcp/relay.globusonline.org/2223; head -c 64 <&3'
# Hang + timeout (exit 124) = the relay protocol is blocked.

# Confirm SSH itself works elsewhere (rules out a broken ssh binary):
timeout 5 ssh -v -p 22 -o BatchMode=yes git@github.com
# Should print "Remote protocol version ..." immediately.
```

Fix paths in priority order:
1. Get IT to allow outbound TCP to `*.globusonline.org` on port `2223`
   (relay control plane) and the GridFTP data ports (`50000-51000` by default).
2. Run GCP from a machine on a less restrictive network — but check first
   with the same `/dev/tcp` probe.
3. **Skip GCP entirely** and upload via the destination collection's HTTPS
   endpoint (if it has one). See below.

### HTTPS upload workaround

Globus Connect Server v5 collections expose a per-collection HTTPS URL
that bypasses the relay/GridFTP machinery completely. Find it with:

```bash
globus gcs collection show <COLLECTION_ID> | grep -i 'HTTPS URL'
# HTTPS URL: https://g-XXXXX.YYYYY.ZZZZZ.data.globus.org
```

Anonymous writes may be enabled (`Disable Anonymous Writes: False`) — in
which case `curl -X PUT --data-binary @file URL/path` just works. Even
with auth required, the token from `globus login` covers it.

Two non-obvious gotchas before scripting a bulk upload:

- **Directories must exist before child PUTs.** `PUT /a/b/file` returns
  `404` if `/a/b/` doesn't exist. Create directories with
  `PUT /a/b/` (trailing slash). `MKCOL` / `POST` return `307` redirects
  and don't create anything useful.
- **Port 443 only.** TLSFTP is also on 443 on these collections, so the
  collection itself is reachable through any firewall that allows HTTPS
  — even though the relay on 2223 isn't.

`upload_https.py` in this repo implements the directory-then-file pattern
with parallel uploads, HEAD-based skipping for resume, and exponential
backoff retries. See the script's `--help` and `skills/globus-jump-upload/SKILL.md`
for the operational playbook captured from this transfer.

## Support

- Globus Documentation: https://docs.globus.org/
- Globus CLI Reference: https://docs.globus.org/cli/
