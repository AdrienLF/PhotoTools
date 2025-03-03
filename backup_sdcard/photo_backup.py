#!/usr/bin/env python3
import os
import sys
import shutil
import hashlib
import datetime
import time
import json
import exifread
import http.server
import socketserver
import threading
import webbrowser
import platform
from pathlib import Path

try:
    import reverse_geocoder as rg
except ImportError:
    print("Installing required dependencies...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reverse_geocoder", "exifread"])
    import reverse_geocoder as rg

import socket

def is_connected(host="8.8.8.8", port=53, timeout=3):
    """
    Check if we have an active internet connection.
    Attempts to connect to Google's public DNS.
    """
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False


# -----------------------------------------------------------
# 1. Simple config load/save functions
# -----------------------------------------------------------
def load_config():
    """
    Reads last-used folders from 'last_folders.json'.
    Returns a dictionary with 'source' and 'destinations'.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_folders.json')
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"source": "", "destinations": []}

def save_config(config):
    """
    Writes the config dictionary to 'last_folders.json'.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_folders.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f)


# Main class for photo backup functionality
class PhotoBackup:
    def __init__(self):
        self.source_dir = ""
        self.destination_dirs = []
        self.status = {
            "total_files": 0,
            "processed_files": 0,
            "current_file": "",
            "est_time_remaining": "",
            "start_time": 0,
            "bytes_total": 0,
            "bytes_processed": 0,
            "complete": False,
            "error": None
        }

    def get_exif_data(self, image_path):
        """Extract EXIF data from an image using exifread."""
        exif_data = {}
        try:
            with open(image_path, 'rb') as img_file:
                tags = exifread.process_file(img_file)
                for tag, value in tags.items():
                    exif_data[tag] = value
        except Exception:
            pass
        return exif_data

    def get_gps_data(self, exif_data):
        """Extract GPS data from EXIF."""
        gps_info = {}
        if 'GPS GPSLatitude' in exif_data and 'GPS GPSLongitude' in exif_data:
            gps_info['GPSLatitude'] = exif_data['GPS GPSLatitude'].values
            gps_info['GPSLatitudeRef'] = exif_data.get('GPS GPSLatitudeRef', 'N')
            gps_info['GPSLongitude'] = exif_data['GPS GPSLongitude'].values
            gps_info['GPSLongitudeRef'] = exif_data.get('GPS GPSLongitudeRef', 'E')
        return gps_info

    def get_coordinates(self, gps_info):
        """Convert GPS coordinates from EXIF to decimal degrees."""
        if not gps_info or 'GPSLatitude' not in gps_info or 'GPSLongitude' not in gps_info:
            return None

        def convert_to_degrees(value):
            d, m, s = [float(v.num) / float(v.den) for v in value]
            return d + (m / 60.0) + (s / 3600.0)

        lat = convert_to_degrees(gps_info['GPSLatitude'])
        lon = convert_to_degrees(gps_info['GPSLongitude'])

        if gps_info.get('GPSLatitudeRef', 'N') == 'S':
            lat = -lat
        if gps_info.get('GPSLongitudeRef', 'E') == 'W':
            lon = -lon

        return (lat, lon)

    def get_location_name(self, image_path):
        """Get location name from GPS coordinates in image.
           When connected to the internet, uses geopy's Nominatim to get ward-level detail.
           Otherwise, falls back to reverse_geocoder."""
        try:
            exif_data = self.get_exif_data(image_path)
            gps_info = self.get_gps_data(exif_data)
            coords = self.get_coordinates(gps_info)

            if not coords:
                return "Unknown"

            # Try to use online geocoding for detailed ward info if connected
            if is_connected():
                try:
                    from geopy.geocoders import Nominatim
                except ImportError:
                    import subprocess
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "geopy"])
                    from geopy.geocoders import Nominatim

                geolocator = Nominatim(user_agent="photo_backup_tool")
                location = geolocator.reverse(f"{coords[0]}, {coords[1]}", language="en")
                if location and location.raw and "address" in location.raw:
                    address = location.raw["address"]
                    # Attempt to use ward-level details; for Japanese addresses, this might be "city_district" or "suburb"
                    if "city_district" in address:
                        return address["city_district"]
                    elif "suburb" in address:
                        return address["suburb"]
                    elif "town" in address:
                        return address["town"]
                    elif "city" in address:
                        return address["city"]
                    elif "county" in address:
                        return address["county"]
                # If the online lookup fails, fall back to reverse_geocoder

            # Fallback to reverse_geocoder if offline or if online lookup fails
            result = rg.search(coords)[0]
            if result.get('name'):
                return result['name']
            elif result.get('admin1'):
                return result['admin1']
            else:
                return result['cc']
        except Exception:
            return "Unknown"

    def get_date_from_image(self, image_path):
        """Extract date from image metadata."""
        try:
            exif_data = self.get_exif_data(image_path)
            date_tag = 'EXIF DateTimeOriginal'
            if date_tag in exif_data:
                date_str = str(exif_data[date_tag])
                date_obj = datetime.datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
                return date_obj.strftime('%Y-%m-%d')
            else:
                mod_time = os.path.getmtime(image_path)
                date_obj = datetime.datetime.fromtimestamp(mod_time)
                return date_obj.strftime('%Y-%m-%d')
        except Exception:
            return datetime.datetime.now().strftime('%Y-%m-%d')


    def calculate_file_hash(self, file_path):
        """Calculate SHA-256 hash of a file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def backup_images(self):
        """Perform the backup operation"""
        self.status["start_time"] = time.time()
        self.status["complete"] = False
        self.status["error"] = None

        try:
            # Get list of all image files
            image_files = []
            for root, _, files in os.walk(self.source_dir):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.tiff', '.bmp', '.heic', ".arw")):
                        image_files.append(os.path.join(root, file))

            self.status["total_files"] = len(image_files)
            self.status["bytes_total"] = sum(os.path.getsize(f) for f in image_files)
            self.status["processed_files"] = 0
            self.status["bytes_processed"] = 0

            for image_path in image_files:
                self.status["current_file"] = os.path.basename(image_path)

                # Get date and location for folder name
                date_str = self.get_date_from_image(image_path)
                location = self.get_location_name(image_path)
                folder_name = f"{date_str} - {location}"

                # Copy file to each destination
                for dest_dir in self.destination_dirs:
                    target_dir = os.path.join(dest_dir, folder_name)
                    os.makedirs(target_dir, exist_ok=True)

                    target_path = os.path.join(target_dir, os.path.basename(image_path))

                    # Only copy if the file doesn't exist or has a different hash
                    if not os.path.exists(target_path) or \
                            self.calculate_file_hash(image_path) != self.calculate_file_hash(target_path):
                        shutil.copy2(image_path, target_path)

                # Update progress
                self.status["processed_files"] += 1
                self.status["bytes_processed"] += os.path.getsize(image_path)

                # Calculate estimated time remaining
                elapsed = time.time() - self.status["start_time"]
                if self.status["processed_files"] > 0:
                    files_per_sec = self.status["processed_files"] / elapsed
                    remaining_files = self.status["total_files"] - self.status["processed_files"]
                    if files_per_sec > 0:
                        est_seconds = remaining_files / files_per_sec
                        m, s = divmod(int(est_seconds), 60)
                        h, m = divmod(m, 60)
                        self.status["est_time_remaining"] = f"{h:d}:{m:02d}:{s:02d}"
                    else:
                        self.status["est_time_remaining"] = "Calculating..."

            self.status["complete"] = True

        except Exception as e:
            self.status["error"] = str(e)


# File dialog helper that ensures it runs on the main thread
class FileDialogHelper:
    @staticmethod
    def get_folder():
        # For macOS, we need a workaround to run Tkinter on the main thread
        if platform.system() == 'Darwin':
            import subprocess
            script = """
import tkinter as tk
from tkinter import filedialog
import sys
root = tk.Tk()
root.withdraw()
folder = filedialog.askdirectory()
sys.stdout.write(folder)
sys.stdout.flush()
"""
            result = subprocess.run([sys.executable, '-c', script],
                                    capture_output=True, text=True)
            return result.stdout
        else:
            # For Windows and Linux, we can use Tkinter directly
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            folder = filedialog.askdirectory()
            root.destroy()
            return folder


# Web server for user interface
class PhotoBackupServer:
    def __init__(self, port=0):
        self.port = port

        # 2. Load config on server start
        self.config = load_config()

        self.backup = PhotoBackup()

        # If config has a remembered source folder, store it
        self.backup.source_dir = self.config.get("source", "")

        # If config has remembered destinations, store them
        self.backup.destination_dirs = self.config.get("destinations", [])

        self.server = None
        self.thread = None

    def find_free_port(self):
        """Find an available port to use"""
        with socketserver.TCPServer(("localhost", 0), None) as s:
            return s.server_address[1]

    def start_server(self):
        """Start the web server in a separate thread"""
        if self.port == 0:
            self.port = self.find_free_port()

        handler = self.create_request_handler()
        self.server = socketserver.TCPServer(("", self.port), handler)

        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        # Open browser
        webbrowser.open(f"http://localhost:{self.port}")

        return self.port

    def stop_server(self):
        """Stop the web server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def create_request_handler(self):
        """Create a request handler for the web server"""
        backup_instance = self.backup
        config_dict = self.config  # capture config for use inside handler
        server_ref = self  # so handler can call save_config etc.

        class PhotoBackupHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args,
                                 directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'),
                                 **kwargs)

            def do_GET(self):
                if self.path == '/':
                    self.path = '/index.html'

                elif self.path == '/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(backup_instance.status).encode())
                    return

                elif self.path == '/browse-source':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()

                    # Get folder using helper
                    folder = FileDialogHelper.get_folder()
                    folder = folder.strip()  # just in case

                    # Immediately store in config if non-empty
                    if folder:
                        config_dict["source"] = folder
                        # Also push to backup instance
                        backup_instance.source_dir = folder
                        # Save config
                        save_config(config_dict)

                    result = {'path': folder if folder else ''}
                    self.wfile.write(json.dumps(result).encode())
                    return

                elif self.path == '/browse-destination':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()

                    # Get folder using helper
                    folder = FileDialogHelper.get_folder()
                    folder = folder.strip()

                    result = {'path': folder if folder else ''}
                    self.wfile.write(json.dumps(result).encode())
                    return

                # 3. Endpoint: get-config
                elif self.path == '/get-config':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(config_dict).encode())
                    return

                return super().do_GET()

            def do_POST(self):
                if self.path == '/start-backup':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    data = json.loads(post_data)

                    backup_instance.source_dir = data['source']
                    backup_instance.destination_dirs = data['destinations']

                    # Start backup in a separate thread
                    threading.Thread(target=backup_instance.backup_images).start()

                    # 4. Also store these to config
                    config_dict["source"] = data['source']
                    config_dict["destinations"] = data['destinations']
                    save_config(config_dict)

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': 'started'}).encode())
                    return

                # 5. Another optional endpoint to save config whenever needed
                elif self.path == '/save-config':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    data = json.loads(post_data)

                    # Update config
                    config_dict["source"] = data.get('source', '')
                    config_dict["destinations"] = data.get('destinations', [])
                    save_config(config_dict)

                    # Also update the backup instance
                    backup_instance.source_dir = config_dict["source"]
                    backup_instance.destination_dirs = config_dict["destinations"]

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'status': 'config saved'}).encode())
                    return

                self.send_response(404)
                self.end_headers()

        return PhotoBackupHandler


# Create the web interface files
def create_web_files():
    # Create web directory if it doesn't exist
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    os.makedirs(web_dir, exist_ok=True)

    # Create index.html
    with open(os.path.join(web_dir, 'index.html'), 'w') as f:
        f.write('''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Photo Backup Tool</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">
        <h1>Photo Backup Tool</h1>

        <div class="setup-panel">
            <div class="form-group">
                <label for="source-folder">Source Folder:</label>
                <div class="input-with-button">
                    <input type="text" id="source-folder" placeholder="Select source folder" readonly>
                    <button id="browse-source">Browse</button>
                </div>
            </div>

            <div class="form-group">
                <label>Destination Folders:</label>
                <div id="destinations-container">
                    <div class="destination-row">
                        <div class="input-with-button">
                            <input type="text" class="destination-folder" placeholder="Select destination folder" readonly>
                            <button class="browse-destination">Browse</button>
                        </div>
                        <button class="remove-destination" style="display: none;">×</button>
                    </div>
                </div>
                <button id="add-destination">Add Another Destination</button>
            </div>

            <button id="start-backup" class="primary-button">Start Backup</button>
        </div>

        <div class="progress-panel" style="display: none;">
            <h2>Backup Progress</h2>

            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill"></div>
                </div>
                <div class="progress-text">0%</div>
            </div>

            <div class="progress-details">
                <p>Current file: <span id="current-file">-</span></p>
                <p>Files: <span id="processed-files">0</span>/<span id="total-files">0</span></p>
                <p>Estimated time remaining: <span id="time-remaining">Calculating...</span></p>
            </div>

            <div class="completion-message" style="display: none;">
                <p>✅ Backup completed successfully!</p>
                <button id="new-backup" class="primary-button">Start New Backup</button>
            </div>

            <div class="error-message" style="display: none;">
                <p>❌ Error: <span id="error-text"></span></p>
                <button id="try-again" class="primary-button">Try Again</button>
            </div>
        </div>
    </div>

    <script src="scripts.js"></script>
</body>
</html>''')

    # Create styles.css
    with open(os.path.join(web_dir, 'styles.css'), 'w') as f:
        f.write('''* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

body {
    background-color: #f5f5f7;
    color: #333;
    line-height: 1.6;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    padding: 40px 20px;
}

h1 {
    text-align: center;
    margin-bottom: 30px;
    color: #1d1d1f;
}

h2 {
    margin-bottom: 20px;
    color: #1d1d1f;
}

.setup-panel, .progress-panel {
    background-color: white;
    border-radius: 12px;
    padding: 30px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
    margin-bottom: 20px;
}

.form-group {
    margin-bottom: 24px;
}

label {
    display: block;
    margin-bottom: 8px;
    font-weight: 500;
}

.input-with-button {
    display: flex;
    width: 100%;
}

input[type="text"] {
    flex-grow: 1;
    padding: 12px 15px;
    border: 1px solid #ddd;
    border-radius: 6px 0 0 6px;
    background-color: #f9f9f9;
    cursor: default;
}

button {
    padding: 12px 20px;
    background-color: #f5f5f7;
    border: 1px solid #ddd;
    border-left: none;
    border-radius: 0 6px 6px 0;
    cursor: pointer;
    transition: background-color 0.2s;
}

button:hover {
    background-color: #eaeaeb;
}

.primary-button {
    display: block;
    width: 100%;
    padding: 12px 20px;
    background-color: #0071e3;
    color: white;
    border: none;
    border-radius: 6px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s;
    margin-top: 10px;
}

.primary-button:hover {
    background-color: #0077ed;
}

.destination-row {
    display: flex;
    align-items: center;
    margin-bottom: 12px;
}

.remove-destination {
    margin-left: 10px;
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background-color: #ff3b30;
    color: white;
    font-size: 18px;
    border: none;
    cursor: pointer;
    transition: background-color 0.2s;
}

.remove-destination:hover {
    background-color: #ff453a;
}

#add-destination {
    border-radius: 6px;
    border: 1px solid #ddd;
    width: auto;
    padding: 8px 15px;
    font-size: 14px;
    margin-top: 5px;
}

.progress-container {
    display: flex;
    align-items: center;
    margin-bottom: 20px;
}

.progress-bar {
    flex-grow: 1;
    height: 10px;
    background-color: #f0f0f0;
    border-radius: 5px;
    overflow: hidden;
    margin-right: 15px;
}

.progress-fill {
    height: 100%;
    background-color: #0071e3;
    width: 0%;
    transition: width 0.3s ease;
}

.progress-text {
    font-weight: 500;
    min-width: 40px;
    text-align: right;
}

.progress-details p {
    margin-bottom: 10px;
    display: flex;
    justify-content: space-between;
}

.completion-message, .error-message {
    text-align: center;
    padding: 20px 0;
}

.completion-message p {
    color: #34c759;
    font-weight: 500;
    font-size: 18px;
    margin-bottom: 20px;
}

.error-message p {
    color: #ff3b30;
    font-weight: 500;
    font-size: 18px;
    margin-bottom: 20px;
}

#new-backup, #try-again {
    max-width: 200px;
    margin: 0 auto;
}''')

    # Create scripts.js
    with open(os.path.join(web_dir, 'scripts.js'), 'w') as f:
        f.write('''document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const sourceFolder = document.getElementById('source-folder');
    const browseSource = document.getElementById('browse-source');
    const destinationsContainer = document.getElementById('destinations-container');
    const addDestination = document.getElementById('add-destination');
    const startBackup = document.getElementById('start-backup');
    const setupPanel = document.querySelector('.setup-panel');
    const progressPanel = document.querySelector('.progress-panel');
    const progressFill = document.querySelector('.progress-fill');
    const progressText = document.querySelector('.progress-text');
    const currentFile = document.getElementById('current-file');
    const processedFiles = document.getElementById('processed-files');
    const totalFiles = document.getElementById('total-files');
    const timeRemaining = document.getElementById('time-remaining');
    const completionMessage = document.querySelector('.completion-message');
    const errorMessage = document.querySelector('.error-message');
    const errorText = document.getElementById('error-text');
    const newBackup = document.getElementById('new-backup');
    const tryAgain = document.getElementById('try-again');
    // Add event listeners to initial destination browse buttons
document.querySelectorAll('.browse-destination').forEach(button => {
    button.addEventListener('click', browseDestination);
});

    // On page load, fetch config and populate
    fetch('/get-config')
        .then(r => r.json())
        .then(config => {
            if (config.source) {
                sourceFolder.value = config.source;
            }
            if (config.destinations && config.destinations.length > 0) {
                // Remove the initial row and re-add properly
                destinationsContainer.innerHTML = '';
                config.destinations.forEach(dest => {
                    addDestinationRow(dest);
                });
            } else {
                // Ensure we have one row if empty
                updateRemoveButtons();
            }
        })
        .catch(err => console.error('Could not load config:', err));

    // Browse for source folder
    browseSource.addEventListener('click', function() {
        fetch('/browse-source')
            .then(response => response.json())
            .then(data => {
                if (data.path) {
                    sourceFolder.value = data.path;
                }
            });
    });

    // Add destination folder row
    function addDestinationRow(folderPath) {
        const row = document.createElement('div');
        row.className = 'destination-row';

        row.innerHTML = `
            <div class="input-with-button">
                <input type="text" class="destination-folder" placeholder="Select destination folder" readonly>
                <button class="browse-destination">Browse</button>
            </div>
            <button class="remove-destination">×</button>
        `;

        destinationsContainer.appendChild(row);

        // Add event listener to new browse button
        row.querySelector('.browse-destination').addEventListener('click', browseDestination);

        // Add event listener to remove button
        row.querySelector('.remove-destination').addEventListener('click', function() {
            destinationsContainer.removeChild(row);
            updateRemoveButtons();
        });

        // If there's a preloaded folder path, set it
        if (folderPath) {
            row.querySelector('.destination-folder').value = folderPath;
        }

        updateRemoveButtons();
    }

    // Add event listeners
    addDestination.addEventListener('click', function() {
        addDestinationRow(); // empty row
    });

    // Browse for destination folder
    function browseDestination() {
        const input = this.parentElement.querySelector('input');

        fetch('/browse-destination')
            .then(response => response.json())
            .then(data => {
                if (data.path) {
                    input.value = data.path;
                }
            });
    }

    // Update remove buttons visibility
    function updateRemoveButtons() {
        const rows = destinationsContainer.querySelectorAll('.destination-row');
        rows.forEach(row => {
            const removeButton = row.querySelector('.remove-destination');
            if (rows.length > 1) {
                removeButton.style.display = 'flex';
            } else {
                removeButton.style.display = 'none';
            }
        });
    }

    // Start backup
    startBackup.addEventListener('click', function() {
        // Validate inputs
        if (!sourceFolder.value) {
            alert('Please select a source folder');
            return;
        }

        const destinations = [];
        document.querySelectorAll('.destination-folder').forEach(input => {
            if (input.value) {
                destinations.push(input.value);
            }
        });

        if (destinations.length === 0) {
            alert('Please select at least one destination folder');
            return;
        }

        // Start backup
        fetch('/start-backup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                source: sourceFolder.value,
                destinations: destinations
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started') {
                setupPanel.style.display = 'none';
                progressPanel.style.display = 'block';
                completionMessage.style.display = 'none';
                errorMessage.style.display = 'none';

                // Start polling for status
                pollStatus();
            }
        });
    });

    // Poll for status
    function pollStatus() {
        fetch('/status')
            .then(response => response.json())
            .then(data => {
                updateProgress(data);

                if (!data.complete && data.error === null) {
                    setTimeout(pollStatus, 500);
                }
            });
    }

    // Update progress UI
    function updateProgress(data) {
        const percent = data.total_files > 0 
            ? Math.round((data.processed_files / data.total_files) * 100) 
            : 0;

        progressFill.style.width = `${percent}%`;
        progressText.textContent = `${percent}%`;

        currentFile.textContent = data.current_file || '-';
        processedFiles.textContent = data.processed_files;
        totalFiles.textContent = data.total_files;
        timeRemaining.textContent = data.est_time_remaining || 'Calculating...';

        if (data.complete) {
            completionMessage.style.display = 'block';
        }

        if (data.error) {
            errorText.textContent = data.error;
            errorMessage.style.display = 'block';
        }
    }

    // New backup button
    newBackup.addEventListener('click', function() {
        progressPanel.style.display = 'none';
        setupPanel.style.display = 'block';

        // Reset progress
        progressFill.style.width = '0%';
        progressText.textContent = '0%';
        currentFile.textContent = '-';
        processedFiles.textContent = '0';
        totalFiles.textContent = '0';
        timeRemaining.textContent = 'Calculating...';
    });

    // Try again button
    tryAgain.addEventListener('click', function() {
        // Just trigger the same start event
        startBackup.click();
    });
});''')

def main():
    print("Setting up Photo Backup Tool...")

    # Create web files
    create_web_files()

    # Check for required dependencies
    try:
        import PIL
        import reverse_geocoder
    except ImportError:
        print("Installing required dependencies...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow", "reverse_geocoder"])

    # Start server
    server = PhotoBackupServer()
    port = server.start_server()

    print(f"\nPhoto Backup Tool is running!")
    print(f"Open your browser at: http://localhost:{port}")
    print("Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop_server()
        print("Done!")


if __name__ == "__main__":
    main()
