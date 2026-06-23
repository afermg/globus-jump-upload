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
If you get permission errors, contact Jess or the Broad Globus admin to ensure you have write access to the collection.

### Large Transfers
For very large datasets, Globus transfers are:
- Fault-tolerant (auto-retry)
- Can resume after interruption
- Run in the background (you can close terminal)
- Optimized for high-throughput

## Support

- Globus Documentation: https://docs.globus.org/
- Globus CLI Reference: https://docs.globus.org/cli/
