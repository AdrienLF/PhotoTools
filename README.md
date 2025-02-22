# Image Analyzer

This tool analyzes images in a folder using Google's SigLIP2 model to:

1. Classify images by orientation (horizontal/vertical/square)
2. Detect and manage duplicate images using visual similarity
3. Store analysis results in a SQLite database

## Features

- Processes images in batches for efficiency
- Uses GPU acceleration when available
- Automatically moves duplicate images to a "duplicates" subfolder
- Maintains a database of analyzed images
- Supports common image formats (JPG, PNG, BMP, GIF, TIFF)

## Requirements

- Docker installed on your system
- Images to analyze in a local folder

## Quick Start

### Windows

1. Place your images in a folder
2. Edit the `analyze_folder.bat` file to point to your images folder
3. Double-click `analyze_folder.bat` to run the analysis

### macOS/Linux

1. Place your images in a folder
2. Edit the `analyze_folder.sh` file to point to your images folder
3. Make the script executable: `chmod +x analyze_folder.sh`
4. Run `./analyze_folder.sh`

## Usage

The analyzer will:

1. Process all images in the specified folder and subfolders
2. Create a database of image information
3. Move any detected duplicates to a "duplicates" subfolder
4. Display a summary of images grouped by orientation

## Technical Details

- Uses Google's SigLIP2 model for image analysis
- Stores embeddings in SQLite with sqlite-vec extension
- Default similarity threshold for duplicates: 0.99 (configurable)
- GPU acceleration used when available

## License

MIT License
