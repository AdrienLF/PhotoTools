@echo off
setlocal

:: Replace this with your images folder path
set IMAGES_FOLDER=C:\Users\YourUsername\Pictures

:: Build the Docker image if it doesn't exist
docker build -t image-analyzer .

:: Run the analysis
docker run --rm -v "%IMAGES_FOLDER%:/data" image-analyzer python sort_photos_ratio.py --folder /data

echo.
echo Analysis complete! Press any key to exit...
pause >nul 