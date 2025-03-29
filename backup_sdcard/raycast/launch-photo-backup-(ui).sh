#!/bin/bash


# Documentation:
# @raycast.description Launches the photo backup tool with the Web UI in a new terminal window.
# @raycast.author Adrien Le Falher
# @raycast.authorURL www.adrienlefalher.com

# Raycast Required Parameters
# @raycast.schemaVersion 1
# @raycast.title Launch Photo Backup (UI)
# @raycast.mode compact
# @raycast.packageName Photo Tools

# Raycast Optional Parameters
# @raycast.icon 🌐
# @raycast.description Launches the photo backup tool with the Web UI in a new terminal window.

# --- Configuration ---
# Directory where the photo_backup.py script is located
SCRIPT_DIR="/Users/adrien/Documents/CODE/PhotoTools/backup_sdcard"
SCRIPT_NAME="photo_backup.py"
# --- Correct path to the Python interpreter inside your UV virtual environment ---
VENV_PYTHON="/Users/adrien/Documents/CODE/PhotoTools/.venv/bin/python3"
# --- End Configuration ---

SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_NAME"

# Check if script file exists
if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Error: Script not found at $SCRIPT_PATH"
  exit 1
fi

# Check if virtual environment Python exists
if [ ! -f "$VENV_PYTHON" ]; then
  echo "Error: Python interpreter not found at $VENV_PYTHON"
  echo "Please ensure the virtual environment at /Users/adrien/Documents/CODE/PhotoTools/.venv exists and is set up correctly."
  exit 1
fi

# Command to execute in the terminal
# 1. Change to the script's directory
# 2. Execute the script using the Python from the virtual environment, adding the --ui flag
COMMAND_TO_RUN="cd '$SCRIPT_DIR' && '$VENV_PYTHON' '$SCRIPT_PATH' --ui"

# Tell Terminal.app to open a new window and run the command
# 'activate' brings Terminal to the front
# 'do script' executes the command in a new terminal session
# The window will remain open showing server logs until you Ctrl+C
osascript <<EOF
tell application "Terminal"
    activate
    do script "$COMMAND_TO_RUN"
end tell
EOF

echo "Photo Backup UI launch command sent to Terminal."
exit 0

