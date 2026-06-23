# Quick Start Guide for Uploading from oppy

This is a streamlined guide for uploading JUMP-lite data from oppy to the Broad Globus collection.

## Step 1: Install and Login

```bash
# Install Globus CLI (if not already installed)
pip install globus-cli

# Login to Globus
globus login
```

## Step 2: Find oppy's Endpoint ID

```bash
# Search for Broad endpoints (oppy should be listed)
globus endpoint search "Broad"

# Or search more specifically
globus endpoint search "oppy"

# List all your accessible endpoints
globus endpoint search --filter-scope my-endpoints
```

Look for the endpoint that corresponds to oppy. Note the UUID (e.g., `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

## Step 3: Transfer Data

Replace `OPPY_ENDPOINT_ID` with the actual endpoint ID from Step 2:

```bash
globus transfer OPPY_ENDPOINT_ID:/home/amunoz/datasets/alan/jump_lite/ \
  20317ea0-5bda-471d-aba2-191c9028f1d8:/images/JUMP-lite/ \
  --recursive \
  --label "JUMP-lite upload from oppy"
```

## Step 4: Monitor Transfer

The transfer runs in the background. Monitor it with:

```bash
# List your recent transfers
globus task list

# Get the task ID from the output above, then:
globus task show TASK_ID

# Or wait for completion
globus task wait TASK_ID --polling-interval 30
```

## Alternative: Use the Web Interface

1. Go to: https://app.globus.org/file-manager
2. In the "Collection" search, enter the oppy endpoint name
3. Navigate to: `/home/amunoz/datasets/alan/jump_lite/`
4. Click "Transfer or Sync to..." button
5. In the destination panel, enter: `20317ea0-5bda-471d-aba2-191c9028f1d8`
6. Navigate to: `/images/JUMP-lite/`
7. Click "Start" to begin transfer

## One-Line Command (if you know oppy's endpoint ID)

```bash
# Replace OPPY_ENDPOINT_ID with actual endpoint ID
globus transfer OPPY_ENDPOINT_ID:/home/amunoz/datasets/alan/jump_lite/ 20317ea0-5bda-471d-aba2-191c9028f1d8:/images/JUMP-lite/ --recursive --label "JUMP-lite from oppy"
```

## Common oppy Endpoint Patterns

If oppy is a Broad Institute machine, the endpoint might be named:
- `Broad Institute endpoint`
- Something with "oppy" in the name
- Check with your sysadmin or Jess for the exact endpoint name

The endpoint ID for "Broad Institute endpoint" is: `41d00dae-772f-40ef-baf7-18be9ff5e066`

Try:
```bash
globus transfer 41d00dae-772f-40ef-baf7-18be9ff5e066:/home/amunoz/datasets/alan/jump_lite/ \
  20317ea0-5bda-471d-aba2-191c9028f1d8:/images/JUMP-lite/ \
  --recursive \
  --label "JUMP-lite from oppy"
```

If that doesn't work, you'll need to find the specific endpoint for oppy.
