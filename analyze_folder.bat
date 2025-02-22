@echo off
setlocal

:: Replace this with your images folder path
set IMAGES_FOLDER="C:\Users\Adrien\Pictures\Street photo"

:: Build the Docker image
docker build -t image-analyzer .

:: Run the analysis with GPU support
docker run --rm --gpus all -v %IMAGES_FOLDER%:/data image-analyzer

echo.
echo Analysis complete! Press any key to exit...
pause >nul 