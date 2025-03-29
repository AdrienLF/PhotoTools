# Photo Backup Tool

A Python script to back up photos from a source directory to one or more destination directories, automatically organizing them into folders based on date and optionally geographic location or a custom suffix. It features duplicate detection and offers both a Command-Line Interface (CLI) and a simple Web User Interface (UI).

## Features

*   **Flexible Backup:** Copy photos from one source to multiple backup destinations simultaneously.
*   **Smart Organization:** Automatically creates folders named by:
    *   `YYYY-MM-DD` (Date only)
    *   `YYYY-MM-DD - LocationName` (Date + Location, requires GPS EXIF data)
    *   `YYYY-MM-DD - CustomSuffix` (Date + User-defined Suffix)
*   **Location Detection:**
    *   Extracts GPS coordinates from image EXIF data.
    *   Uses `geopy` (if available and online) for detailed location names (city, town, suburb, etc.).
    *   Falls back to the offline `reverse_geocoder` library for location lookup if offline or `geopy` is unavailable.
*   **Duplicate Prevention:** Avoids copying files that already exist in the target folder with the same name, size, and content (SHA-256 hash check).
*   **Two Modes:**
    *   **CLI:** Interactive command-line operation, suitable for scripting or server usage. Shows progress bar.
    *   **Web UI:** Simple browser-based interface for easier interaction (`--ui` flag).
*   **Performance:** Uses multi-threading to speed up file processing (hashing, EXIF reading, copying).
*   **Configuration:** Remembers last used source/destination folders and settings in `last_folders.json`.
*   **Dependency Management:** Attempts to auto-install required Python packages (`pip`) if missing (requires internet). Manual installation is also supported and recommended, especially using virtual environments.

## Requirements

*   **Python:** Version 3.7 or higher recommended.
*   **Package Installer:** `pip` (usually included with Python) or `uv` (a faster alternative).
*   **Python Libraries:**
    *   `exifread`: To read EXIF metadata from images.
    *   `reverse_geocoder`: For offline location lookup from GPS coordinates.
    *   `Pillow`: Image processing library (often a dependency for EXIF handling).
    *   `geopy` (Optional but Recommended): For more accurate online location lookup.
*   **Internet Connection:**
    *   Required for the initial installation of dependencies (if done automatically or manually).
    *   Required for *online* geocoding using `geopy`. Offline geocoding works without internet.
*   **Tkinter** (for UI mode file browsing):
    *   Usually included with Python on Windows.
    *   May need to be installed separately on Linux distributions (e.g., `sudo apt-get update && sudo apt-get install python3-tk`).
    *   Handled via a subprocess workaround on macOS, should work out-of-the-box.

## Installation / Setup

1.  **Download the Script:**
    *   Clone the repository:
        ```bash
        git clone <repository_url>
        cd <repository_directory>
        ```
    *   Or, download `photo_backup.py` directly.

2.  **Set up Dependencies (Choose ONE method):**

    *   **Method A: Automatic Installation (Convenient)**
        *   The script will try to detect and install missing packages using `pip` the first time you run it.
        *   Simply try running the script: `python photo_backup.py`
        *   You might need appropriate permissions for `pip` to install packages globally, or run into issues. **Using a virtual environment (Method B/C) is generally safer and recommended.**

    *   **Method B: Manual Installation using `pip` (Recommended)**
        *   **Create a Virtual Environment:** (Optional but highly recommended)
            ```bash
            # Navigate to the directory containing photo_backup.py
            python -m venv venv
            # Activate the environment
            # On Windows:
            .\venv\Scripts\activate
            # On macOS/Linux:
            source venv/bin/activate
            ```
        *   **Install Packages:**
            ```bash
            pip install --upgrade pip
            pip install exifread reverse_geocoder Pillow geopy
            ```
            *(Note: `geopy` is optional but recommended for better location names)*

    *   **Method C: Manual Installation using `uv` (Faster Alternative)**
        *   **Install `uv`:** Follow the official `uv` installation guide: [https://github.com/astral-sh/uv#installation](https://github.com/astral-sh/uv#installation) (e.g., `pip install uv` or use their standalone installers).
        *   **Create a Virtual Environment:** (Optional but highly recommended, `uv` integrates well)
            ```bash
            # Navigate to the directory containing photo_backup.py
            python -m venv venv # Or uv venv venv
            # Activate the environment
            # On Windows:
            .\venv\Scripts\activate
            # On macOS/Linux:
            source venv/bin/activate
            ```
        *   **Install Packages using `uv`:** (Run *inside* the activated environment)
            ```bash
            uv pip install exifread reverse_geocoder Pillow geopy
            ```
            *(Note: `geopy` is optional but recommended for better location names)*

3.  **Install Tkinter (If Needed for UI):**
    *   If you plan to use the UI mode (`--ui`) and the file browser doesn't work (especially on Linux), you might need Tkinter.
    *   On Debian/Ubuntu: `sudo apt-get update && sudo apt-get install python3-tk`
    *   On Fedora: `sudo dnf install python3-tkinter`
    *   Check your distribution's package manager for the correct package name.

## Usage Tutorial

You can run the tool in two ways: Command-Line Interface (CLI) or Web User Interface (UI).

---

### 1. CLI Mode (Default)

This mode is interactive and runs directly in your terminal.

*   **How to Run:**
    ```bash
    # If using a virtual environment, make sure it's activated first!
    # source venv/bin/activate  OR  .\venv\Scripts\activate

    python photo_backup.py
    ```

*   **Interactive Prompts:** The script will guide you:
    1.  **Source Directory:** It will show the last used source (if any) and ask if you want to use it. If not, or if it's the first time, it will prompt you to enter the full path to the folder containing the photos you want to back up.
    2.  **Destination Directories:** It will show the last used destinations (if any) and ask to reuse them. If not, it will prompt you to enter the full path for *each* backup destination folder. Press Enter without typing a path (after adding at least one) to finish adding destinations. Destination folders must exist beforehand.
    3.  **Folder Naming Options:** You'll be asked how to name the subfolders created in the destination(s):
        *   `1`: **Date + Location** (e.g., `2023-10-27 - Tokyo`). Requires photos to have GPS data in EXIF. Needs internet for best results (`geopy`), otherwise uses offline data (`reverse_geocoder`).
        *   `2`: **Date + Custom Suffix** (e.g., `2023-10-27 - Holiday`). You will be prompted to enter the suffix text.
        *   `3`: **Date Only** (e.g., `2023-10-27`).
    4.  **Confirmation:** The script displays the chosen configuration and asks for final confirmation before starting.

*   **Progress:** During the backup, you'll see a progress bar updating in the terminal, showing:
    *   Percentage complete.
    *   Number of files processed / total files.
    *   Data processed / total data size (in MB).
    *   Estimated Time Remaining (ETA).
    *   The name of the file currently being processed.
    *   Any errors encountered will be printed above the progress bar.

*   **Completion:** Once finished, it will print a summary message (success or finished with errors).

*   **Cancel:** Press `Ctrl+C` at any time to stop the process.

---

### 2. Web UI Mode

This mode provides a graphical interface accessible through your web browser.

*   **How to Run:**
    ```bash
    # If using a virtual environment, make sure it's activated first!
    # source venv/bin/activate  OR  .\venv\Scripts\activate

    python photo_backup.py --ui
    ```

*   **What Happens:**
    *   A local web server starts in the background.
    *   The script will print the URL (usually `http://localhost:<port_number>`).
    *   It will attempt to automatically open this URL in your default web browser. If it fails, manually copy and paste the URL into your browser.

*   **Using the Interface:**
    1.  **Source Folder:** Click "Browse" to select the folder containing your photos. Your selection will be saved for future use.
    2.  **Destination Folders:**
        *   Click "Browse" on a destination row to select a backup folder.
        *   Click "Add Another Destination" to add more backup locations.
        *   Click the "×" button next to a destination to remove it (only visible if more than one destination exists).
        *   Selected destinations are saved for future use.
    3.  **Folder Naming Options:** Choose how the backup folders should be named using the radio buttons:
        *   **Date + Location:** Uses GPS data.
        *   **Date + Custom Suffix:** Enables the text input field next to it where you must enter your desired suffix.
        *   **Date Only:** Just uses the date.
    4.  **Start Backup:** Once configured, click the "Start Backup" button.
    5.  **Progress Panel:** The setup panel will be replaced by a progress panel showing the backup status, current file, percentage, counts, data size, and ETA, similar to the CLI mode but graphically.
    6.  **Completion/Error:** When the backup finishes, a success message or an error message (with details) will be displayed.
    7.  **New Backup:** After completion or error, click "Start New Backup" or "Configure New Backup" to return to the setup screen.

*   **How to Stop:** Go back to the terminal where you launched the script and press `Ctrl+C`. This will shut down the web server. Closing the browser tab *does not* stop the server or an ongoing backup.

---

## Configuration File (`last_folders.json`)

*   This file is automatically created/updated in the same directory as `photo_backup.py`.
*   It stores the last used source directory, destination directories, and folder naming preferences in JSON format.
*   This allows the script (in both CLI and UI modes) to remember your settings for the next time you run it, saving you setup time.
*   You can safely delete this file if you want to start with a clean configuration (it will be recreated). You can also manually edit it if needed, but be careful with the JSON syntax.

## Troubleshooting

*   **Dependency Errors:** If automatic installation fails or you get `ImportError`, use the manual installation steps (Method B or C above), preferably within a virtual environment. Ensure `pip` or `uv` is up-to-date.
*   **UI File Browser Fails:** If the "Browse" buttons in the UI don't work, you might be missing the `Tkinter` system package (see Requirements/Installation). Check the terminal for error messages.
*   **Permission Denied Errors:** The script needs read access to the source directory/files and write access to the destination directories. Ensure you have the necessary permissions. Run the script as a user with appropriate rights.
*   **Location Name "Unknown":** This usually means the photo lacks GPS EXIF data, the GPS data is invalid, or both `geopy` (online) and `reverse_geocoder` (offline) failed to find a match for the coordinates. Check if your camera saves GPS data. For `geopy`, ensure you have an internet connection.
*   **Slow Performance:** Backup speed depends heavily on the number/size of files, the speed of your source/destination drives (SSDs are much faster than HDDs), and your CPU (for hashing/EXIF reading).

## License

MIT License