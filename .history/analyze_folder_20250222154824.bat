@echo off
setlocal

:: Replace this with your images folder path
set IMAGES_FOLDER="C:\Users\Adrien\Pictures\Street photo"

:: Build the Docker image
docker build -t image-analyzer .

:: Run the analysis
docker run --rm -v %IMAGES_FOLDER%:/data image-analyzer

echo.
echo Analysis complete! Press any key to exit...
pause >nul 