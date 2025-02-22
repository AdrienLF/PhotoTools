#!/bin/bash

# Replace this with your images folder path
IMAGES_FOLDER="$HOME/Pictures"

# Build the Docker image if it doesn't exist
docker build -t image-analyzer .

# Run the analysis
docker run --rm -v "$IMAGES_FOLDER:/data" image-analyzer python sort_photos_ratio.py --folder /data 