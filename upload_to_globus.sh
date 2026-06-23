#!/bin/bash
# Upload JUMP-lite data to Broad Globus collection

set -e

# Configuration
DEST_COLLECTION="20317ea0-5bda-471d-aba2-191c9028f1d8"
DEST_PATH="/images/JUMP-lite/"
SOURCE_PATH="/home/amunoz/datasets/alan/jump_lite/"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Globus JUMP-lite Upload Script ===${NC}\n"

# Check if globus CLI is installed
if ! command -v globus &> /dev/null; then
    echo -e "${RED}Error: globus CLI not found${NC}"
    echo "Install with: pip install globus-cli"
    exit 1
fi

# Check authentication
echo "Checking Globus authentication..."
if ! globus whoami &> /dev/null; then
    echo -e "${YELLOW}Not authenticated. Running globus login...${NC}"
    globus login
fi

echo -e "${GREEN}✓ Authenticated as: $(globus whoami)${NC}\n"

# Get source endpoint
echo "Please provide your source endpoint ID:"
echo "  Option 1: Run 'globus endpoint search --filter-scope my-endpoints' to find your local endpoint"
echo "  Option 2: Run 'globus endpoint search \"Broad\"' to find Broad endpoints"
echo ""
read -p "Source Endpoint ID: " SOURCE_ENDPOINT

if [ -z "$SOURCE_ENDPOINT" ]; then
    echo -e "${RED}Error: Source endpoint ID is required${NC}"
    exit 1
fi

# Optionally modify source path
read -p "Source path [$SOURCE_PATH]: " CUSTOM_SOURCE_PATH
SOURCE_PATH=${CUSTOM_SOURCE_PATH:-$SOURCE_PATH}

# Start transfer
echo -e "\n${GREEN}Starting transfer...${NC}"
echo "  From: ${SOURCE_ENDPOINT}:${SOURCE_PATH}"
echo "  To:   ${DEST_COLLECTION}:${DEST_PATH}"

TASK_ID=$(globus transfer \
    "${SOURCE_ENDPOINT}:${SOURCE_PATH}" \
    "${DEST_COLLECTION}:${DEST_PATH}" \
    --recursive \
    --label "JUMP-lite upload $(date +%Y-%m-%d_%H:%M:%S)" \
    --format json | jq -r '.task_id')

if [ -z "$TASK_ID" ]; then
    echo -e "${RED}Error: Failed to start transfer${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Transfer started${NC}"
echo "  Task ID: $TASK_ID"
echo ""
echo "Monitor your transfer:"
echo "  globus task show $TASK_ID"
echo "  globus task wait $TASK_ID"
echo ""
echo "Or visit: https://app.globus.org/activity/$TASK_ID"
