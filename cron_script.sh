#!/bin/bash

# Define variables
SCRIPT_NAME="main.py"
SCRIPT_DIR="/home/user/visa_rescheduler_aws"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/$(date +'%Y%m%d_%H%M%S').log"

# Create the logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Find and kill any running instances of the script
pkill -f "$SCRIPT_NAME"

# Change to the script directory
cd "$SCRIPT_DIR" || exit

# Activate the virtual environment and run the script, logging output
/home/user/visa_rescheduler_aws/venv/bin/python "$SCRIPT_NAME" >> "$LOG_FILE" 2>&1

