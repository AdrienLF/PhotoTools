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
from concurrent.futures import ThreadPoolExecutor
import queue
import argparse # <-- Added for argument parsing
import socket

# --- Early Dependency Check ---
try:
    import reverse_geocoder as rg
    import PIL # Check for Pillow as well, needed by some EXIF libraries indirectly sometimes
except ImportError:
    print("Installing required dependencies (reverse_geocoder, exifread, Pillow)...")
    import subprocess
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "reverse_geocoder", "exifread", "Pillow"])
        import reverse_geocoder as rg
        print("Dependencies installed successfully.")
    except Exception as e:
        print(f"Error installing dependencies: {e}")
        print("Please install them manually: pip install reverse_geocoder exifread Pillow")
        sys.exit(1)
# --- End Dependency Check ---


def is_connected(host="8.8.8.8", port=53, timeout=3):
    """
    Check if we have an active internet connection.
    Attempts to connect to Google's public DNS.
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(None) # Reset default timeout


# -----------------------------------------------------------
# 1. Simple config load/save functions
# -----------------------------------------------------------
CONFIG_FILE = 'last_folders.json'

def get_config_path():
    """Gets the absolute path to the config file."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)

def load_config():
    """
    Reads last-used folders from 'last_folders.json'.
    Returns a dictionary with 'source', 'destinations', 'append_location', 'folder_suffix'.
    """
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                # Ensure default keys exist
                config = json.load(f)
                config.setdefault("source", "")
                config.setdefault("destinations", [])
                config.setdefault("append_location", True)
                config.setdefault("folder_suffix", "")
                return config
        except json.JSONDecodeError:
            print(f"Warning: Config file {config_path} is corrupted. Using defaults.")
            # Optionally back up the corrupted file
            # shutil.move(config_path, config_path + ".corrupted")
            return {"source": "", "destinations": [], "append_location": True, "folder_suffix": ""}
    return {"source": "", "destinations": [], "append_location": True, "folder_suffix": ""}

def save_config(config):
    """
    Writes the config dictionary to 'last_folders.json'.
    """
    config_path = get_config_path()
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4) # Added indent for readability
    except IOError as e:
        print(f"Error saving config file {config_path}: {e}")


# Main class for photo backup functionality
class PhotoBackup:
    # Added cli_mode flag
    def __init__(self, cli_mode=False):
        self.source_dir = ""
        self.destination_dirs = []
        self.append_location = True
        self.folder_suffix = ""
        self.cli_mode = cli_mode # <-- Store CLI mode
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
        # Cache for location data to avoid redundant lookups
        self.location_cache = {}
        # Cache for file hashes to avoid recalculating
        self.hash_cache = {}
        # Cache for date information
        self.date_cache = {}
        # Status update queue
        self.status_queue = queue.Queue()
        # Number of worker threads
        self.num_workers = max(4, os.cpu_count() or 4)
        # Flag to control geocoding (set based on user choice)
        self._should_geocode = True # Default, will be updated based on config/choice
        self._internet_checked = False
        self._has_internet = False


    def _check_internet(self):
        """Checks internet connection once."""
        if not self._internet_checked:
            self._has_internet = is_connected()
            self._internet_checked = True
            if self.cli_mode and self.append_location and not self._has_internet:
                print("Warning: No internet connection. Falling back to offline location data (may be less precise).")
        return self._has_internet

    def get_exif_data(self, image_path):
        """Extract EXIF data from an image using exifread."""
        # Check cache first (though less likely for raw EXIF)
        # if image_path in self.exif_cache: return self.exif_cache[image_path]
        exif_data = {}
        try:
            with open(image_path, 'rb') as img_file:
                # Stop processing certain tags for speed if not needed (e.g., MakerNote)
                tags = exifread.process_file(img_file, stop_tag='MakerNote', details=False)
                # Alternative: process_file(img_file, details=False) is faster
                for tag, value in tags.items():
                    # Handle potential encoding issues gracefully
                    try:
                       exif_data[tag] = value
                    except Exception:
                        pass # Ignore tags that cause issues during processing
        except FileNotFoundError:
             print(f"Error: File not found during EXIF read: {image_path}") # More specific error
        except Exception as e:
            # Log less critical errors without stopping, maybe just for verbose mode
            # print(f"Warning: Could not read EXIF for {os.path.basename(image_path)}: {e}")
            pass
        # self.exif_cache[image_path] = exif_data # Cache if needed
        return exif_data

    def get_gps_data(self, exif_data):
        """Extract GPS data from EXIF."""
        gps_info = {}
        # Check for the necessary tags efficiently
        lat_tag = 'GPS GPSLatitude'
        lon_tag = 'GPS GPSLongitude'
        if lat_tag in exif_data and lon_tag in exif_data:
            try:
                gps_info['GPSLatitude'] = exif_data[lat_tag].values
                gps_info['GPSLatitudeRef'] = exif_data.get('GPS GPSLatitudeRef', 'N').values[0] # Safer access
                gps_info['GPSLongitude'] = exif_data[lon_tag].values
                gps_info['GPSLongitudeRef'] = exif_data.get('GPS GPSLongitudeRef', 'E').values[0] # Safer access
                return gps_info
            except (AttributeError, IndexError, TypeError):
                 # Handle cases where GPS tags are present but malformed
                 # print(f"Warning: Malformed GPS data found.")
                 return None
        return None

    def get_coordinates(self, gps_info):
        """Convert GPS coordinates from EXIF to decimal degrees."""
        if not gps_info:
            return None

        try:
            def convert_to_degrees(value):
                # Check if value is already processed (e.g., from PIL)
                if isinstance(value, (float, int)): return value
                # Original exifread format
                if isinstance(value, list) and len(value) == 3:
                    try:
                        d = float(value[0].num) / float(value[0].den)
                        m = float(value[1].num) / float(value[1].den)
                        s = float(value[2].num) / float(value[2].den)
                        return d + (m / 60.0) + (s / 3600.0)
                    except (ZeroDivisionError, AttributeError, TypeError):
                        return None # Invalid ratio data
                return None # Unexpected format

            lat_val = convert_to_degrees(gps_info['GPSLatitude'])
            lon_val = convert_to_degrees(gps_info['GPSLongitude'])

            if lat_val is None or lon_val is None:
                return None

            # Apply reference N/S, E/W
            if gps_info.get('GPSLatitudeRef') == 'S': lat_val = -lat_val
            if gps_info.get('GPSLongitudeRef') == 'W': lon_val = -lon_val

            # Basic sanity check for coordinate range
            if not (-90 <= lat_val <= 90 and -180 <= lon_val <= 180):
                # print(f"Warning: Calculated coordinates out of range: ({lat_val}, {lon_val})")
                return None

            return (lat_val, lon_val)

        except (KeyError, TypeError, IndexError) as e:
            # print(f"Error converting GPS info: {e}") # Debugging
            return None


    def get_location_name(self, image_path):
        """Get location name from GPS coordinates in image.
           Uses online geopy if available and connected, otherwise reverse_geocoder."""
        # Only proceed if geocoding is enabled for this run
        if not self._should_geocode:
            return "Unknown"

        # Check cache first
        if image_path in self.location_cache:
            return self.location_cache[image_path]

        location_result = "Unknown" # Default
        try:
            exif_data = self.get_exif_data(image_path)
            gps_info = self.get_gps_data(exif_data)
            coords = self.get_coordinates(gps_info)

            if not coords:
                self.location_cache[image_path] = location_result
                return location_result

            # Try online geocoding first if connected
            if self._check_internet():
                try:
                    from geopy.geocoders import Nominatim
                    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
                except ImportError:
                    if self.cli_mode: print("Geopy not installed, cannot use online geocoding. 'pip install geopy'")
                    # Fall through to offline method
                else:
                    try:
                        geolocator = Nominatim(user_agent="photo_backup_tool_cli_v1") # Unique agent
                        # Increased timeout, language preference
                        location = geolocator.reverse(f"{coords[0]}, {coords[1]}", language="en", timeout=10)
                        if location and location.raw and "address" in location.raw:
                            address = location.raw["address"]
                            # Prioritize more specific fields if they exist
                            fields = ["neighbourhood", "suburb", "village", "hamlet", "city_district", "town", "city", "county", "state", "country"]
                            for field in fields:
                                if field in address:
                                    location_result = address[field]
                                    break # Use the first specific field found
                            self.location_cache[image_path] = location_result
                            return location_result
                        # If online lookup gave no useful result, fall through
                    except (GeocoderTimedOut, GeocoderServiceError) as geo_err:
                        if self.cli_mode: print(f"Warning: Online geocoding failed: {geo_err}. Falling back to offline.")
                    except Exception as e:
                        if self.cli_mode: print(f"Warning: Error during online geocoding: {e}. Falling back to offline.")


            # Fallback to reverse_geocoder (offline)
            try:
                # Use mode 2 for faster performance with slightly less accuracy if needed
                # results = rg.search(coords, mode=2)
                results = rg.search(coords) # Default mode 1
                if results:
                    result = results[0]
                    # Prioritize name, admin2, admin1, cc
                    location_result = result.get('name') or result.get('admin2') or result.get('admin1') or result.get('cc', 'Unknown')
                else:
                    location_result = "Unknown" # Offline lookup returned nothing
            except Exception as rg_err:
                 if self.cli_mode: print(f"Warning: Offline reverse geocoding failed: {rg_err}")
                 location_result = "Unknown" # Error during offline lookup


        except FileNotFoundError:
            # Already handled in get_exif_data, but good to have a catch here too
             location_result = "Unknown"
        except Exception as e:
            # Catch-all for unexpected errors during location finding
            if self.cli_mode: print(f"Warning: Unexpected error getting location for {os.path.basename(image_path)}: {e}")
            location_result = "Unknown"

        self.location_cache[image_path] = location_result
        return location_result


    def get_date_from_image(self, image_path):
        """Extract date from image metadata (EXIF preferred) or file modification time."""
        if image_path in self.date_cache:
            return self.date_cache[image_path]

        date_str_result = None
        try:
            # Try EXIF first
            exif_data = self.get_exif_data(image_path)
            date_tags = ['EXIF DateTimeOriginal', 'Image DateTime', 'EXIF DateTimeDigitized']
            for tag in date_tags:
                if tag in exif_data:
                    date_str = str(exif_data[tag])
                    # Handle various potential date formats (add more if needed)
                    for fmt in ('%Y:%m:%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                        try:
                            date_obj = datetime.datetime.strptime(date_str.split('.')[0], fmt) # Ignore fractional seconds
                            date_str_result = date_obj.strftime('%Y-%m-%d')
                            break # Found a valid date
                        except ValueError:
                            continue # Try next format
                if date_str_result: break # Found date in EXIF

            # If no valid EXIF date, use file modification time
            if not date_str_result:
                try:
                    mod_time = os.path.getmtime(image_path)
                    # Basic check: avoid dates far in the future or past (e.g., Unix epoch)
                    if mod_time > 0 and mod_time < time.time() + 86400: # Allow up to 1 day in future
                        date_obj = datetime.datetime.fromtimestamp(mod_time)
                        date_str_result = date_obj.strftime('%Y-%m-%d')
                    else: # Fallback to current date if mod time seems invalid
                        date_str_result = datetime.datetime.now().strftime('%Y-%m-%d')

                except OSError: # Handle file system errors getting mod time
                     date_str_result = datetime.datetime.now().strftime('%Y-%m-%d')


        except FileNotFoundError:
             date_str_result = datetime.datetime.now().strftime('%Y-%m-%d')
             if self.cli_mode: print(f"Warning: File not found while getting date: {image_path}")
        except Exception as e:
            # Fallback for any other error
            date_str_result = datetime.datetime.now().strftime('%Y-%m-%d')
            if self.cli_mode: print(f"Warning: Could not determine date for {os.path.basename(image_path)}, using current date. Error: {e}")

        # Ensure we always return *some* date string
        if date_str_result is None:
            date_str_result = datetime.datetime.now().strftime('%Y-%m-%d')

        self.date_cache[image_path] = date_str_result
        return date_str_result


    def calculate_file_hash(self, file_path):
        """Calculate SHA-256 hash of a file"""
        if file_path in self.hash_cache:
            return self.hash_cache[file_path]

        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                # Read in larger chunks for potentially faster I/O
                for chunk in iter(lambda: f.read(65536), b''):
                    hash_sha256.update(chunk)
            result = hash_sha256.hexdigest()
            self.hash_cache[file_path] = result
            return result
        except FileNotFoundError:
            if self.cli_mode: print(f"Error: File not found during hash calculation: {file_path}")
            return None
        except IOError as e:
            if self.cli_mode: print(f"Error reading file for hash calculation {file_path}: {e}")
            return None
        except Exception as e:
            if self.cli_mode: print(f"Unexpected error calculating hash for {file_path}: {e}")
            return None


    def process_image(self, image_path):
        """Process a single image file"""
        try:
            base_name = os.path.basename(image_path)
            # Get date and location/suffix for folder name
            date_str = self.get_date_from_image(image_path)

            # Determine folder name based on settings
            if self.append_location:
                location = self.get_location_name(image_path)
                # Sanitize location name for file systems
                safe_location = "".join(c for c in location if c.isalnum() or c in (' ', '-', '_')).strip()
                folder_name = f"{date_str} - {safe_location}" if safe_location != "Unknown" else date_str
            elif self.folder_suffix:
                 # Sanitize suffix as well
                safe_suffix = "".join(c for c in self.folder_suffix if c.isalnum() or c in (' ', '-', '_')).strip()
                folder_name = f"{date_str} - {safe_suffix}" if safe_suffix else date_str
            else: # Just the date
                folder_name = date_str

            # Get file size once
            try:
                file_size = os.path.getsize(image_path)
            except FileNotFoundError:
                 self.status_queue.put({"error": f"Error: Source file disappeared: {base_name}", "size": 0})
                 return False # File vanished
            except OSError as e:
                 self.status_queue.put({"error": f"Error getting size of {base_name}: {e}", "size": 0})
                 return False


            source_hash = None # Calculate only if needed for comparison
            copied_to_any = False

            # Copy file to each destination
            for dest_dir in self.destination_dirs:
                try:
                    target_dir_path = Path(dest_dir) / folder_name
                    target_dir_path.mkdir(parents=True, exist_ok=True)

                    target_path = target_dir_path / base_name
                    target_path_str = str(target_path) # Keep str version for os.path/shutil

                    # --- Comparison Logic ---
                    should_copy = True
                    if target_path.exists():
                        try:
                            target_size = target_path.stat().st_size
                            if target_size == file_size:
                                # Sizes match, compare hashes (calculate source hash only now if needed)
                                if source_hash is None:
                                    source_hash = self.calculate_file_hash(image_path)
                                    if source_hash is None: # Hash calculation failed
                                        raise Exception(f"Could not calculate source hash for {base_name}")

                                target_hash = self.calculate_file_hash(target_path_str)
                                if target_hash is None: # Hash calculation failed
                                     raise Exception(f"Could not calculate target hash for {target_path_str}")


                                if source_hash == target_hash:
                                    should_copy = False # Identical file exists
                            # else: files exist but sizes differ, so we should copy (overwrite)

                        except OSError as e:
                            # Error accessing target file, maybe log and try copying anyway
                            self.status_queue.put({"error": f"Warning: Could not check existing target {target_path_str}: {e}. Will attempt copy.", "size": 0})
                            should_copy = True
                        except Exception as e: # Catch hash calculation errors here too
                            self.status_queue.put({"error": f"Warning: Error comparing hashes for {base_name} in {dest_dir}: {e}. Will attempt copy.", "size": 0})
                            should_copy = True

                    # --- Copy File ---
                    if should_copy:
                        try:
                             # Use copy2 to preserve metadata
                            shutil.copy2(image_path, target_path_str)
                            copied_to_any = True
                        except Exception as copy_err:
                             # Log error for this specific destination, but continue to others
                             self.status_queue.put({"error": f"Error copying {base_name} to {target_path_str}: {copy_err}", "size": 0})


                except OSError as e:
                     # Error creating directory or other OS issue for this destination
                     self.status_queue.put({"error": f"Error processing destination {dest_dir} for {base_name}: {e}", "size": 0})
                except Exception as e:
                     # General error for this destination
                     self.status_queue.put({"error": f"Unexpected error for {base_name} in {dest_dir}: {e}", "size": 0})


            # Update progress only once per source file, regardless of how many dests it went to
            self.status_queue.put({
                "file": base_name,
                "size": file_size
                # "copied": copied_to_any # Could add flag if needed
            })

            return True # Indicate the file was processed (even if copy failed somewhere)

        except Exception as e:
            # Broad exception catch for the whole process_image function
            self.status_queue.put({
                "error": f"Critical error processing {os.path.basename(image_path)}: {str(e)}",
                "size": 0
            })
            return False


    def status_updater(self):
        """Thread to update status information and print CLI progress."""
        files_processed_since_last_print = 0
        last_print_time = time.time()

        while not self.status.get("complete", False): # Use get for safety
            try:
                update = self.status_queue.get(timeout=0.2) # Shorter timeout for responsiveness

                if "error" in update:
                    if self.cli_mode:
                        # Print error immediately in CLI mode, ensuring it's on a new line
                        print(f"\nERROR: {update['error']}", file=sys.stderr)
                    else:
                        # In UI mode, let the status endpoint report the error
                        if self.status["error"] is None: # Store only the first error for UI simplicity
                           self.status["error"] = update["error"]
                        else: # Log subsequent errors if needed
                           print(f"Additional Error: {update['error']}", file=sys.stderr)

                elif "file" in update: # Successful file processing update
                    self.status["current_file"] = update["file"]
                    self.status["processed_files"] += 1
                    self.status["bytes_processed"] += update["size"]
                    files_processed_since_last_print += 1

                    # --- Calculate ETA ---
                    elapsed = time.time() - self.status["start_time"]
                    if self.status["processed_files"] > 0 and elapsed > 1: # Avoid division by zero/instability at start
                        # Option 1: Files per second
                        # files_per_sec = self.status["processed_files"] / elapsed
                        # remaining_files = self.status["total_files"] - self.status["processed_files"]
                        # if files_per_sec > 0:
                        #     est_seconds = remaining_files / files_per_sec

                        # Option 2: Bytes per second (often more stable for varying file sizes)
                        bytes_per_sec = self.status["bytes_processed"] / elapsed
                        remaining_bytes = self.status["bytes_total"] - self.status["bytes_processed"]
                        if bytes_per_sec > 0:
                             est_seconds = remaining_bytes / bytes_per_sec
                        else:
                            est_seconds = float('inf') # Avoid division by zero if no bytes yet

                        if est_seconds != float('inf'):
                            m, s = divmod(int(est_seconds), 60)
                            h, m = divmod(m, 60)
                            self.status["est_time_remaining"] = f"{h:d}:{m:02d}:{s:02d}"
                        else:
                            self.status["est_time_remaining"] = "Calculating..."
                    else:
                        self.status["est_time_remaining"] = "Calculating..."


                    # --- CLI Progress Output ---
                    # Update CLI progress bar less frequently to reduce overhead/flicker
                    now = time.time()
                    if self.cli_mode and (files_processed_since_last_print >= 5 or now - last_print_time > 1.0 or self.status["processed_files"] == self.status["total_files"]):
                        percent = (self.status["processed_files"] / self.status["total_files"] * 100) if self.status["total_files"] > 0 else 0
                        bar_len = 30
                        filled_len = int(bar_len * self.status["processed_files"] // self.status["total_files"]) if self.status["total_files"] > 0 else 0
                        bar = '█' * filled_len + '-' * (bar_len - filled_len)

                        # Truncate long filenames
                        display_file = (update["file"][:35] + '...') if len(update["file"]) > 38 else update["file"]

                        # Format bytes
                        processed_mb = self.status["bytes_processed"] / (1024 * 1024)
                        total_mb = self.status["bytes_total"] / (1024 * 1024)

                        # Use carriage return `\r` to overwrite the line. Add spaces at the end to clear previous longer lines.
                        print(f'\rProgress: [{bar}] {percent:.1f}% ({self.status["processed_files"]}/{self.status["total_files"]}) | {processed_mb:.1f}/{total_mb:.1f} MB | ETA: {self.status["est_time_remaining"]} | File: {display_file:<40}', end='')
                        sys.stdout.flush() # Ensure it prints immediately

                        files_processed_since_last_print = 0
                        last_print_time = now


                self.status_queue.task_done()
            except queue.Empty:
                # Queue is empty, check if main process marked as complete
                if self.status.get("complete", False):
                     break # Exit loop if processing is done and queue is empty
                # Otherwise, just loop again after timeout
                pass
            except Exception as e:
                 # Unexpected error in status updater itself
                 print(f"\nError in status updater: {e}", file=sys.stderr)
                 # Consider breaking or logging more details

        # --- Final CLI Output ---
        if self.cli_mode:
             # Print a newline to move off the progress bar line
             print()
             # Final status message based on outcome
             if self.status.get("error"):
                 print(f"Backup finished with errors. See messages above.", file=sys.stderr)
             elif self.status.get("complete"):
                 print(f"Backup complete! {self.status['processed_files']}/{self.status['total_files']} files processed.")
             else: # Should not happen if loop logic is correct
                 print("Backup process finished.")


    def backup_images(self):
        """Perform the backup operation using multiple threads"""
        self.status["start_time"] = time.time()
        self.status["complete"] = False
        self.status["error"] = None
        self.status["processed_files"] = 0
        self.status["bytes_processed"] = 0
        self.status["total_files"] = 0
        self.status["bytes_total"] = 0
        self.status["current_file"] = "Initializing..."
        self.status["est_time_remaining"] = "Calculating..."

        # Clear caches at the start of each backup run
        self.location_cache = {}
        self.hash_cache = {}
        self.date_cache = {}
        self._internet_checked = False # Reset internet check flag

        # Set geocoding flag based on settings
        self._should_geocode = self.append_location

        try:
            if not self.source_dir or not os.path.isdir(self.source_dir):
                raise ValueError(f"Source directory is invalid or not set: {self.source_dir}")
            if not self.destination_dirs:
                 raise ValueError("No destination directories specified.")
            for dest in self.destination_dirs:
                if not dest or not os.path.isdir(dest):
                     # Allow creation? For now, require existing dest dirs.
                     # os.makedirs(dest, exist_ok=True)
                     raise ValueError(f"Destination directory is invalid or does not exist: {dest}")


            if self.cli_mode:
                print(f"Starting backup from: {self.source_dir}")
                print(f"To destinations: {', '.join(self.destination_dirs)}")
                folder_mode = "Date + Location" if self.append_location else (f"Date + Suffix '{self.folder_suffix}'" if self.folder_suffix else "Date Only")
                print(f"Folder naming: {folder_mode}")
                print(f"Using {self.num_workers} worker threads.")
                print("Scanning source directory...")


            # Get list of all image files and calculate total size
            image_files = []
            total_size = 0
            valid_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.tiff', '.tif', '.bmp', '.heic', '.heif', ".arw", ".cr2", ".nef", ".dng", ".orf", ".rw2", ".pef", ".srw") # Added more raw types
            for root, _, files in os.walk(self.source_dir, onerror=lambda e: print(f"Warning: Cannot access directory {e.filename}: {e.strerror}", file=sys.stderr)):
                for file in files:
                    if file.lower().endswith(valid_extensions):
                        file_path = os.path.join(root, file)
                        try:
                            # Basic check if file is readable and get size
                            file_stat = os.stat(file_path)
                            image_files.append(file_path)
                            total_size += file_stat.st_size
                        except OSError as e:
                            print(f"Warning: Cannot access file {file_path}: {e.strerror}", file=sys.stderr)


            self.status["total_files"] = len(image_files)
            self.status["bytes_total"] = total_size

            if self.status["total_files"] == 0:
                print("No image files found in the source directory.")
                self.status["complete"] = True
                self.status["current_file"] = ""
                return # Nothing to do

            if self.cli_mode:
                print(f"Found {self.status['total_files']} image files, total size {total_size / (1024*1024):.2f} MB.")
                print("Starting processing...")


            # Start status updater thread
            # Make it non-daemon for CLI so we can potentially wait for its final print
            status_thread = threading.Thread(target=self.status_updater, daemon=not self.cli_mode)
            status_thread.start()

            # Process files with thread pool
            # Using 'with' ensures threads are joined before proceeding
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                # map will process items and collect results (or exceptions)
                # We don't strictly need the results here, just the execution
                futures = [executor.submit(self.process_image, img_path) for img_path in image_files]
                # Wait for all tasks to complete
                for future in futures:
                     try:
                         future.result() # Check for exceptions raised within threads
                     except Exception as e:
                         # This catches errors *raised* by process_image, not those put in queue
                         print(f"\nError during thread execution: {e}", file=sys.stderr)
                         if self.status["error"] is None: self.status["error"] = str(e)


            # Signal completion to status updater *after* all tasks are submitted and done
            self.status["complete"] = True

            # Wait for the status queue to be fully processed (all updates handled)
            self.status_queue.join()

            # If in CLI mode, wait for the status updater thread to finish its final print
            if self.cli_mode:
                 status_thread.join(timeout=5) # Give it a few seconds to finish printing

            # Play completion sound (maybe only for UI or make it optional?)
            # if not self.cli_mode:
            #    # Consider a platform-agnostic way or remove
            #    try:
            #        # Example using system beep (might not work everywhere)
            #        # print('\a') # ASCII Bell
            #        pass
            #    except Exception:
            #        pass # Ignore sound errors

        except ValueError as ve: # Config/Setup errors
             self.status["error"] = str(ve)
             if self.cli_mode: print(f"Configuration Error: {ve}", file=sys.stderr)
        except Exception as e:
            self.status["error"] = f"An unexpected error occurred: {str(e)}"
            if self.cli_mode: print(f"\nCritical Backup Error: {e}", file=sys.stderr)
            # Ensure status is marked complete even on error to stop updater
            self.status["complete"] = True
        finally:
             # Ensure complete is set true so status endpoint reflects final state
             self.status["complete"] = True
             # Ensure the status updater thread knows to stop eventually
             # (it checks self.status['complete'])



# --- UI Specific Code ---

# File dialog helper (Keep as is, only used by UI)
class FileDialogHelper:
    # ... (FileDialogHelper class code remains unchanged) ...
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
# Make it appear on top
root.call('wm', 'attributes', '.', '-topmost', True)
folder = filedialog.askdirectory()
sys.stdout.write(folder if folder else '') # Handle cancel
sys.stdout.flush()
"""
            try:
                # Adding a timeout in case the tk dialog hangs
                result = subprocess.run([sys.executable, '-c', script],
                                        capture_output=True, text=True, timeout=300, check=False) # 5 min timeout
                if result.returncode == 0:
                    return result.stdout.strip()
                else:
                    print(f"Error in file dialog subprocess: {result.stderr}")
                    return None
            except subprocess.TimeoutExpired:
                 print("Error: File dialog timed out.")
                 return None
            except Exception as e:
                 print(f"Error running file dialog helper: {e}")
                 return None

        else:
            # For Windows and Linux, we can use Tkinter directly
            # Ensure tkinter is available
            try:
                import tkinter as tk
                from tkinter import filedialog
            except ImportError:
                 print("Error: Tkinter is required for the file browser UI. Please install it (e.g., 'sudo apt-get install python3-tk' on Debian/Ubuntu).")
                 return None

            root = tk.Tk()
            try:
                root.withdraw()
                # Make it appear on top
                root.attributes('-topmost', True)
                folder = filedialog.askdirectory()
            finally:
                # Ensure Tk root is destroyed even if dialog fails
                 root.destroy()
            return folder if folder else None # Return None if cancelled


# Web server for user interface
class PhotoBackupServer:
    # ... (PhotoBackupServer class code remains largely unchanged) ...
    # Minor change: Instantiate PhotoBackup with cli_mode=False
    def __init__(self, port=0):
        self.port = port
        self.config = load_config()
        # Explicitly set cli_mode=False for UI instance
        self.backup = PhotoBackup(cli_mode=False)

        self.backup.source_dir = self.config.get("source", "")
        self.backup.destination_dirs = self.config.get("destinations", [])
        self.backup.append_location = self.config.get("append_location", True)
        self.backup.folder_suffix = self.config.get("folder_suffix", "")

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
        # Allow address reuse
        socketserver.TCPServer.allow_reuse_address = True
        try:
            self.server = socketserver.TCPServer(("", self.port), handler)
        except OSError as e:
            print(f"Error starting server on port {self.port}: {e}", file=sys.stderr)
            print("The port might be in use. Try stopping other instances or choose a different port.")
            sys.exit(1)


        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        print(f"\nPhoto Backup Tool UI is running!")
        print(f"Attempting to open browser at: http://localhost:{self.port}")
        # Give server a moment to start before opening browser
        time.sleep(0.5)
        try:
            webbrowser.open(f"http://localhost:{self.port}")
        except Exception as e:
             print(f"Could not automatically open web browser: {e}")
             print(f"Please open it manually: http://localhost:{self.port}")


        return self.port

    def stop_server(self):
        """Stop the web server"""
        if self.server:
            print("\nShutting down web server...")
            self.server.shutdown() # Stop serve_forever loop
            self.server.server_close() # Release port
            print("Web server stopped.")
        if self.thread and self.thread.is_alive():
             self.thread.join(timeout=2) # Wait briefly for thread to exit


    def create_request_handler(self):
        """Create a request handler for the web server"""
        backup_instance = self.backup
        config_dict = self.config
        # server_ref = self # Not strictly needed anymore

        class PhotoBackupHandler(http.server.SimpleHTTPRequestHandler):
            # Ensure web files are served from correct dir relative to script
            web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')

            def __init__(self, *args, **kwargs):
                # Serve files from the 'web' subdirectory
                super().__init__(*args, directory=self.web_dir, **kwargs)

            # --- GET handlers ---
            def do_GET(self):
                if self.path == '/':
                    self.path = '/index.html'
                    # Check if index.html exists
                    if not os.path.exists(os.path.join(self.web_dir, 'index.html')):
                         self.send_error(404, "Error: index.html not found in web directory.")
                         return

                elif self.path == '/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.send_header('Cache-Control', 'no-cache') # Prevent caching of status
                    self.end_headers()
                    # Ensure status is JSON serializable (basic types)
                    safe_status = backup_instance.status.copy()
                    # Convert non-serializable types if necessary (e.g., custom objects)
                    # For this script, the status dict seems okay.
                    self.wfile.write(json.dumps(safe_status).encode('utf-8'))
                    return

                elif self.path == '/browse-source' or self.path == '/browse-destination':
                    # Use the helper class to get folder
                    folder = FileDialogHelper.get_folder()
                    result = {'path': folder if folder else ''} # Send empty string if cancelled

                    # If browsing source and a folder was selected, update config
                    if self.path == '/browse-source' and folder:
                        config_dict["source"] = folder
                        backup_instance.source_dir = folder # Update instance too
                        save_config(config_dict) # Save immediately

                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                    return

                elif self.path == '/get-config':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(config_dict).encode('utf-8'))
                    return

                # Fallback to SimpleHTTPRequestHandler for static files (index.html, css, js)
                # Check if requested file exists in web dir
                # self.path includes the leading '/'
                requested_path = os.path.abspath(os.path.join(self.web_dir, self.path.lstrip('/')))
                if not requested_path.startswith(os.path.abspath(self.web_dir)):
                    self.send_error(403, "Forbidden") # Prevent directory traversal
                    return
                if not os.path.exists(requested_path) or not os.path.isfile(requested_path):
                     # If it's not a known API endpoint or an existing file, return 404
                     # This prevents errors if browser requests e.g. /favicon.ico
                     # Keep this check *after* API endpoints
                     if self.path not in ['/status', '/browse-source', '/browse-destination', '/get-config', '/start-backup', '/save-config']:
                         # self.send_error(404, "File not found")
                         # Silently ignore requests for non-existent files like favicon.ico
                         # To avoid console noise. Send a minimal response.
                         self.send_response(404)
                         self.send_header('Content-type', 'text/plain')
                         self.end_headers()
                         self.wfile.write(b'Not Found')
                         return
                     # Else, it might be a POST request handled below, let it pass

                # Serve static file using parent class method
                try:
                    return super().do_GET()
                except BrokenPipeError:
                    # Handle cases where client disconnects during transfer
                    self.log_message("Client disconnected during GET request.")
                except Exception as e:
                     self.send_error(500, f"Error serving file: {e}")
                     self.log_error(f"Error serving GET {self.path}: {e}")


            # --- POST handlers ---
            def do_POST(self):
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    if content_length == 0:
                        self.send_error(400, "Bad Request: Content-Length required")
                        return
                    post_data = self.rfile.read(content_length).decode('utf-8')
                    data = json.loads(post_data)
                except json.JSONDecodeError:
                    self.send_error(400, "Bad Request: Invalid JSON")
                    return
                except Exception as e:
                     self.send_error(500, f"Error reading request body: {e}")
                     return

                if self.path == '/start-backup':
                    try:
                        source = data.get('source')
                        destinations = data.get('destinations', [])
                        append_loc = data.get('append_location', True)
                        folder_sfx = data.get('folder_suffix', '')

                        # Basic validation
                        if not source or not isinstance(destinations, list) or not destinations:
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({'status': 'error', 'message': 'Missing source or destinations'}).encode('utf-8'))
                            return

                        backup_instance.source_dir = source
                        backup_instance.destination_dirs = destinations
                        backup_instance.append_location = append_loc
                        backup_instance.folder_suffix = folder_sfx if not append_loc else "" # Only use suffix if location is off

                        # Save config before starting
                        config_dict["source"] = source
                        config_dict["destinations"] = destinations
                        config_dict["append_location"] = append_loc
                        config_dict["folder_suffix"] = folder_sfx
                        save_config(config_dict)

                        # Start backup in a separate thread so HTTP request returns immediately
                        # Check if already running? Maybe prevent concurrent runs from UI.
                        if backup_instance.status.get("start_time", 0) > 0 and not backup_instance.status.get("complete", True):
                             self.send_response(409) # Conflict
                             self.send_header('Content-type', 'application/json')
                             self.end_headers()
                             self.wfile.write(json.dumps({'status': 'error', 'message': 'Backup already in progress'}).encode('utf-8'))
                             return


                        threading.Thread(target=backup_instance.backup_images, daemon=True).start()

                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'status': 'started'}).encode('utf-8'))
                    except Exception as e:
                         self.send_response(500)
                         self.send_header('Content-type', 'application/json')
                         self.end_headers()
                         self.wfile.write(json.dumps({'status': 'error', 'message': f'Failed to start backup: {e}'}).encode('utf-8'))
                    return

                # Removed /save-config endpoint as config is saved on browse/start
                # Add other POST endpoints here if needed

                # Default POST response if path not matched
                self.send_response(404)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'error', 'message': 'Endpoint not found'}).encode('utf-8'))


            # Override log message to reduce noise or customize format
            # def log_message(self, format, *args):
            #    # Example: Suppress logging for static file requests
            #    # if self.path.endswith(('.css', '.js', '.html', '.ico')):
            #    #    return
            #    super().log_message(format, *args)


        return PhotoBackupHandler


# Create the web interface files (only if needed)
def create_web_files():
    """Creates the necessary HTML, CSS, JS files in a 'web' subdirectory."""
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    os.makedirs(web_dir, exist_ok=True)
    print("Ensuring web interface files exist...")

    # --- index.html ---
    # Added logic to disable suffix input when location is checked
    index_html_content = '''<!DOCTYPE html>
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
                    <!-- Destination rows added dynamically -->
                </div>
                <button id="add-destination">Add Another Destination</button>
            </div>

            <fieldset class="form-group naming-options">
                <legend>Folder Naming Options:</legend>
                <div class="radio-group">
                    <label class="radio-label">
                        <input type="radio" name="naming_option" id="append-location" value="location" checked>
                        Date + Location <small>(Needs Internet/GPS)</small>
                    </label>
                </div>
                 <div class="radio-group">
                    <label class="radio-label">
                        <input type="radio" name="naming_option" id="use-suffix" value="suffix">
                        Date + Custom Suffix
                    </label>
                    <input type="text" id="folder-suffix" placeholder="Enter custom suffix" disabled>
                 </div>
                 <div class="radio-group">
                     <label class="radio-label">
                         <input type="radio" name="naming_option" id="date-only" value="date">
                         Date Only
                     </label>
                 </div>
            </fieldset>


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

            <p><strong>Status:</strong> <span id="status-message">Initializing...</span></p>

            <div class="progress-details">
                <p>Current file: <span id="current-file">-</span></p>
                <p>Files: <span id="processed-files">0</span>/<span id="total-files">0</span></p>
                <p>Size: <span id="processed-size">0 MB</span>/<span id="total-size">0 MB</span></p>
                <p>Estimated time remaining: <span id="time-remaining">Calculating...</span></p>
            </div>

            <div class="completion-message" style="display: none;">
                <p>✅ Backup completed successfully!</p>
                <button id="new-backup" class="primary-button">Start New Backup</button>
            </div>

            <div class="error-message" style="display: none;">
                <p>❌ Error: <span id="error-text"></span></p>
                <button id="try-again" class="primary-button">Configure New Backup</button> <!-- Changed text -->
            </div>
        </div>
    </div>

    <script src="scripts.js"></script>
</body>
</html>'''
    with open(os.path.join(web_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html_content)

    # --- styles.css ---
    # Minor style adjustments for radio buttons/fieldset
    styles_css_content = '''* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

body {
    background-color: #f5f5f7;
    color: #333;
    line-height: 1.6;
    padding-bottom: 50px; /* Ensure content doesn't touch bottom */
}

.container {
    max-width: 700px; /* Slightly narrower */
    margin: 30px auto; /* Reduced top margin */
    padding: 20px;
    background-color: white;
    border-radius: 12px;
    box-shadow: 0 4px Gist Coplot20px rgba(0, 0, 0, 0.08);
}

h1 {
    text-align: center;
    margin-bottom: 25px;
    color: #1d1d1f;
    font-size: 1.8em;
}

h2 {
    margin-bottom: 15px;
    color: #1d1d1f;
    font-size: 1.4em;
    border-bottom: 1px solid #eee;
    padding-bottom: 10px;
}

.setup-panel, .progress-panel {
    padding: 20px;
    margin-bottom: 20px;
}

.form-group {
    margin-bottom: 20px;
}
.form-group:last-child {
    margin-bottom: 0;
}


label {
    display: block;
    margin-bottom: 6px;
    font-weight: 500;
    font-size: 0.95em;
}

.input-with-button {
    display: flex;
    width: 100%;
}

input[type="text"], input[type="text"]:read-only {
    flex-grow: 1;
    padding: 10px 12px; /* Slightly smaller padding */
    border: 1px solid #ccc;
    border-radius: 6px;
    background-color: #fff; /* White background */
    font-size: 0.95em;
    color: #333;
}
input[type="text"]:read-only {
     background-color: #f8f8f8; /* Slightly grey for readonly */
     cursor: default;
}


button {
    padding: 10px 18px; /* Adjust padding */
    background-color: #e9e9ed; /* Lighter grey */
    color: #333;
    border: 1px solid #ccc;
    border-left: none;
    border-radius: 0 6px 6px 0;
    cursor: pointer;
    transition: background-color 0.2s;
    font-size: 0.9em;
    white-space: nowrap; /* Prevent browse button text wrapping */
}
button:hover {
    background-color: #dcdce1;
}

.primary-button {
    display: block;
    width: 100%;
    padding: 12px 20px;
    background-color: #0071e3;
    color: white;
    border: none;
    border-radius: 6px;
    font-size: 1em;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.2s;
    margin-top: 15px; /* Space above primary button */
}
.primary-button:hover {
    background-color: #0077ed;
}
.primary-button:disabled {
    background-color: #a0cffc; /* Lighter blue when disabled */
    cursor: not-allowed;
}


.destination-row {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
}
.destination-row:last-child {
     margin-bottom: 0;
}

.remove-destination {
    margin-left: 8px;
    width: 32px; /* Smaller remove button */
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background-color: #ff5c5c; /* Adjusted red */
    color: white;
    font-size: 16px; /* Smaller X */
    font-weight: bold;
    border: none;
    cursor: pointer;
    transition: background-color 0.2s;
    flex-shrink: 0; /* Prevent shrinking */
    padding: 0; /* Reset padding */
}
.remove-destination:hover {
    background-color: #ff3b30;
}

#add-destination {
    border-radius: 6px;
    border: 1px solid #ccc;
    background-color: #f8f8f8;
    width: auto;
    padding: 8px 15px;
    font-size: 0.9em;
    margin-top: 8px; /* Space above add button */
    border-left: 1px solid #ccc; /* Add left border back */
}
#add-destination:hover {
     background-color: #eee;
}


/* Naming Options */
.naming-options {
    border: 1px solid #eee;
    border-radius: 6px;
    padding: 15px;
    margin-top: 10px;
}
.naming-options legend {
    font-weight: 500;
    padding: 0 5px;
    font-size: 0.95em;
}
.radio-group {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
    gap: 8px; /* Space between radio and label/input */
}
.radio-group:last-child {
     margin-bottom: 0;
}
.radio-label {
    display: flex; /* Use flex for alignment */
    align-items: center;
    gap: 6px; /* Space between radio button and text */
    margin-bottom: 0; /* Remove default label margin */
    cursor: pointer;
    font-weight: normal; /* Normal weight for radio labels */
    font-size: 0.95em;
}
.radio-label input[type="radio"] {
    margin-right: 4px; /* Small space */
    flex-shrink: 0;
     /* Custom styling could go here */
}
.radio-label small {
     color: #666;
     font-size: 0.85em;
}
#folder-suffix {
    margin-left: 5px; /* Space after radio group */
    max-width: 200px; /* Limit width */
    flex-grow: 0; /* Don't let it grow too much */
    padding: 8px 10px; /* Smaller padding */
    font-size: 0.9em;
}
#folder-suffix:disabled {
    background-color: #f0f0f0;
    cursor: not-allowed;
    border-color: #ddd;
}


/* Progress Panel */
.progress-container {
    display: flex;
    align-items: center;
    margin-bottom: 15px;
    gap: 15px;
}

.progress-bar {
    flex-grow: 1;
    height: 12px; /* Slightly thicker bar */
    background-color: #e9e9ed;
    border-radius: 6px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    background-color: #0071e3;
    width: 0%;
    transition: width 0.2s ease-out; /* Faster transition */
    border-radius: 6px; /* Match parent */
}

.progress-text {
    font-weight: 500;
    min-width: 50px; /* Ensure space for 100.0% */
    text-align: right;
    font-size: 0.95em;
}

#status-message {
    font-weight: 500;
    margin-bottom: 15px;
    display: block; /* Make it block level */
}

.progress-details {
    font-size: 0.9em;
    color: #555;
    margin-bottom: 15px;
    padding-left: 5px; /* Indent details slightly */
}
.progress-details p {
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between; /* Align text left/right */
    gap: 10px; /* Space between label and value */
}
.progress-details p span {
    text-align: right; /* Align values to the right */
    min-width: 80px; /* Give space for values */
}


.completion-message, .error-message {
    text-align: center;
    padding: 20px 0 10px 0; /* Adjust padding */
}

.completion-message p {
    color: #34c759;
    font-weight: 500;
    font-size: 1.2em; /* Slightly larger */
    margin-bottom: 15px;
}

.error-message p {
    color: #ff3b30;
    font-weight: 500;
    font-size: 1.1em;
    margin-bottom: 15px;
}
.error-message span {
     display: block; /* Put error text on new line */
     font-weight: normal;
     font-size: 0.95em;
     margin-top: 5px;
     max-height: 100px; /* Limit error display height */
     overflow-y: auto; /* Allow scrolling for long errors */
     background-color: #fff0f0; /* Light red background */
     padding: 5px;
     border-radius: 4px;
     border: 1px solid #ffcccc;
}


#new-backup, #try-again {
    max-width: 250px; /* Wider button */
    margin: 0 auto;
}'''
    with open(os.path.join(web_dir, 'styles.css'), 'w', encoding='utf-8') as f:
        f.write(styles_css_content)

    # --- scripts.js ---
    # Updated to handle radio buttons for naming, add/remove logic, reset state
    scripts_js_content = '''document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const sourceFolderInput = document.getElementById('source-folder');
    const browseSourceButton = document.getElementById('browse-source');
    const destinationsContainer = document.getElementById('destinations-container');
    const addDestinationButton = document.getElementById('add-destination');
    const startBackupButton = document.getElementById('start-backup');

    // Naming options elements
    const appendLocationRadio = document.getElementById('append-location');
    const useSuffixRadio = document.getElementById('use-suffix');
    const dateOnlyRadio = document.getElementById('date-only');
    const folderSuffixInput = document.getElementById('folder-suffix');
    const namingOptionRadios = document.querySelectorAll('input[name="naming_option"]');

    // Panels and Progress elements
    const setupPanel = document.querySelector('.setup-panel');
    const progressPanel = document.querySelector('.progress-panel');
    const progressFill = document.querySelector('.progress-fill');
    const progressText = document.querySelector('.progress-text');
    const statusMessage = document.getElementById('status-message');
    const currentFileSpan = document.getElementById('current-file');
    const processedFilesSpan = document.getElementById('processed-files');
    const totalFilesSpan = document.getElementById('total-files');
    const processedSizeSpan = document.getElementById('processed-size');
    const totalSizeSpan = document.getElementById('total-size');
    const timeRemainingSpan = document.getElementById('time-remaining');
    const completionMessageDiv = document.querySelector('.completion-message');
    const errorMessageDiv = document.querySelector('.error-message');
    const errorTextSpan = document.getElementById('error-text');
    const newBackupButton = document.getElementById('new-backup');
    const tryAgainButton = document.getElementById('try-again'); // Renamed from 'try-again' in HTML logic

    let statusInterval = null; // To store the interval ID for polling

    // --- Initial Setup ---

    // Function to format bytes to MB/GB etc.
    function formatBytes(bytes, decimals = 1) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    // Function to add a destination row
    function addDestinationRow(folderPath = '') {
        const row = document.createElement('div');
        row.className = 'destination-row';

        row.innerHTML = `
            <div class="input-with-button">
                <input type="text" class="destination-folder" placeholder="Select destination folder" readonly>
                <button class="browse-destination">Browse</button>
            </div>
            <button class="remove-destination" aria-label="Remove destination">×</button>
        `;

        destinationsContainer.appendChild(row);
        const input = row.querySelector('.destination-folder');
        if (folderPath) {
            input.value = folderPath;
        }

        // Add event listeners to new buttons
        row.querySelector('.browse-destination').addEventListener('click', browseDestination);
        row.querySelector('.remove-destination').addEventListener('click', function() {
            destinationsContainer.removeChild(row);
            updateRemoveButtonsVisibility();
        });

        updateRemoveButtonsVisibility();
    }

    // Function to update visibility of remove buttons
    function updateRemoveButtonsVisibility() {
        const rows = destinationsContainer.querySelectorAll('.destination-row');
        rows.forEach((row, index) => {
            const removeButton = row.querySelector('.remove-destination');
            if (rows.length > 1) {
                removeButton.style.display = 'flex'; // Use flex to match CSS
            } else {
                removeButton.style.display = 'none';
            }
        });
        // Add a default row if none exist after removal
        if (rows.length === 0) {
             addDestinationRow();
        }
    }

     // Function to reset the UI to the initial setup state
    function resetUI() {
        // Stop polling if active
        if (statusInterval) {
            clearInterval(statusInterval);
            statusInterval = null;
        }

        // Show setup, hide progress
        setupPanel.style.display = 'block';
        progressPanel.style.display = 'none';
        completionMessageDiv.style.display = 'none';
        errorMessageDiv.style.display = 'none';

        // Reset progress indicators
        progressFill.style.width = '0%';
        progressText.textContent = '0%';
        statusMessage.textContent = 'Initializing...';
        currentFileSpan.textContent = '-';
        processedFilesSpan.textContent = '0';
        totalFilesSpan.textContent = '0';
        processedSizeSpan.textContent = '0 MB';
        totalSizeSpan.textContent = '0 MB';
        timeRemainingSpan.textContent = 'Calculating...';
        errorTextSpan.textContent = '';

        // Re-enable start button
        startBackupButton.disabled = false;

        // Don't clear source/destination inputs, keep config values
        // But maybe reload config in case it changed elsewhere?
        // loadConfig(); // Optional: reload config state
    }


    // --- Event Listeners ---

    browseSourceButton.addEventListener('click', function() {
        // Disable button temporarily to prevent double clicks
        browseSourceButton.disabled = true;
        fetch('/browse-source')
            .then(response => response.ok ? response.json() : Promise.reject('Network error'))
            .then(data => {
                if (data && data.path) {
                    sourceFolderInput.value = data.path;
                } else if (data && data.path === '') {
                     // User cancelled - do nothing, keep existing value
                } else {
                     console.warn("Browse source failed or returned unexpected data:", data);
                }
            })
            .catch(err => console.error('Error browsing source:', err))
            .finally(() => {
                browseSourceButton.disabled = false; // Re-enable button
            });
    });

    addDestinationButton.addEventListener('click', () => addDestinationRow());

    // Use event delegation for destination browse buttons
    destinationsContainer.addEventListener('click', function(event) {
        if (event.target.classList.contains('browse-destination')) {
            browseDestination.call(event.target); // Call browseDestination with the button as 'this'
        }
    });

    // Handler for browsing destination (needs to know which input to update)
    function browseDestination() {
        const button = this; // 'this' is the clicked button
        const input = button.closest('.destination-row').querySelector('.destination-folder');

        button.disabled = true; // Disable button temporarily

        fetch('/browse-destination')
            .then(response => response.ok ? response.json() : Promise.reject('Network error'))
            .then(data => {
                if (data && data.path) {
                    input.value = data.path;
                    // Optionally save config here if desired
                    // saveCurrentConfig();
                } else if (data && data.path === '') {
                    // User cancelled
                } else {
                    console.warn("Browse destination failed or returned unexpected data:", data);
                }
            })
            .catch(err => console.error('Error browsing destination:', err))
            .finally(() => {
                 button.disabled = false; // Re-enable button
            });
    }

    // Event listeners for naming option radio buttons
    namingOptionRadios.forEach(radio => {
        radio.addEventListener('change', handleNamingOptionChange);
    });

    function handleNamingOptionChange() {
         if (useSuffixRadio.checked) {
            folderSuffixInput.disabled = false;
            folderSuffixInput.focus();
         } else {
             folderSuffixInput.disabled = true;
             folderSuffixInput.value = ''; // Clear suffix if not used
         }
         // Maybe save config preference immediately?
         // saveCurrentConfig();
    }

    // Start Backup Button
    startBackupButton.addEventListener('click', function() {
        // Validate inputs
        const source = sourceFolderInput.value.trim();
        if (!source) {
            alert('Please select a source folder.');
            return;
        }

        const destinations = Array.from(destinationsContainer.querySelectorAll('.destination-folder'))
                                 .map(input => input.value.trim())
                                 .filter(path => path !== ''); // Get non-empty, trimmed paths

        if (destinations.length === 0) {
            alert('Please select at least one valid destination folder.');
            return;
        }

        // Determine naming options
        let appendLoc = false;
        let folderSfx = '';
        if (appendLocationRadio.checked) {
            appendLoc = true;
        } else if (useSuffixRadio.checked) {
            appendLoc = false;
            folderSfx = folderSuffixInput.value.trim();
             if (!folderSfx) {
                 alert('Please enter a custom suffix or choose another naming option.');
                 folderSuffixInput.focus();
                 return;
             }
        } else { // Date Only
             appendLoc = false;
             folderSfx = '';
        }


        // Disable button, show progress panel
        startBackupButton.disabled = true;
        setupPanel.style.display = 'none';
        progressPanel.style.display = 'block';
        completionMessageDiv.style.display = 'none';
        errorMessageDiv.style.display = 'none';
        statusMessage.textContent = 'Starting backup...';

        // Prepare data payload
        const backupData = {
            source: source,
            destinations: destinations,
            append_location: appendLoc,
            folder_suffix: folderSfx
        };

        // Start backup via POST request
        fetch('/start-backup', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json' // Expect JSON back
            },
            body: JSON.stringify(backupData)
        })
        .then(response => {
            if (!response.ok) {
                // Try to get error message from response body
                return response.json().then(errData => {
                   throw new Error(errData.message || `HTTP error! Status: ${response.status}`);
                }).catch(() => {
                   // If body cannot be parsed or no message, throw generic error
                   throw new Error(`HTTP error! Status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'started') {
                statusMessage.textContent = 'Backup in progress...';
                // Start polling for status updates
                pollStatus();
            } else {
                 // Should not happen if response was ok, but handle defensively
                 throw new Error(data.message || 'Failed to start backup.');
            }
        })
        .catch(error => {
            console.error('Error starting backup:', error);
            statusMessage.textContent = 'Error starting backup.';
            errorTextSpan.textContent = error.message || 'Unknown error occurred.';
            errorMessageDiv.style.display = 'block';
            // Don't reset UI immediately, let user see the error
            // resetUI(); // Re-enable setup panel on error? Maybe not.
            startBackupButton.disabled = false; // Re-enable start button on error
        });
    });


    // New Backup / Try Again Buttons
    newBackupButton.addEventListener('click', resetUI);
    tryAgainButton.addEventListener('click', resetUI); // Now just resets to config screen


    // --- Status Polling and UI Update ---

    function pollStatus() {
        // Clear previous interval if any (safety check)
        if (statusInterval) clearInterval(statusInterval);

        statusInterval = setInterval(() => {
            fetch('/status')
                .then(response => {
                    if (!response.ok) { throw new Error(`Status fetch failed: ${response.status}`); }
                    return response.json();
                })
                .then(status => {
                    updateProgressUI(status);

                    // Stop polling if complete or error occurred
                    if (status.complete || status.error) {
                        clearInterval(statusInterval);
                        statusInterval = null;
                        startBackupButton.disabled = false; // Re-enable start button once done/failed

                        if (status.error) {
                             statusMessage.textContent = 'Backup failed!';
                             errorTextSpan.textContent = status.error;
                             errorMessageDiv.style.display = 'block';
                             completionMessageDiv.style.display = 'none';
                        } else if (status.complete) {
                             statusMessage.textContent = 'Backup finished!';
                             errorMessageDiv.style.display = 'none';
                             completionMessageDiv.style.display = 'block';
                        }
                    }
                })
                .catch(error => {
                    console.error('Error polling status:', error);
                    statusMessage.textContent = 'Error fetching status.';
                    // Optionally stop polling on error, or keep trying?
                    // clearInterval(statusInterval);
                    // statusInterval = null;
                    // errorTextSpan.textContent = 'Connection lost or server error.';
                    // errorMessageDiv.style.display = 'block';
                });
        }, 1000); // Poll every 1 second
    }

    function updateProgressUI(status) {
        const total = status.total_files || 0;
        const processed = status.processed_files || 0;
        const percent = total > 0 ? Math.round((processed / total) * 100) : (status.complete ? 100 : 0);

        progressFill.style.width = `${percent}%`;
        progressText.textContent = `${percent}%`;

        // Update status message based on state
        if (status.error) {
             statusMessage.textContent = 'Backup failed!';
        } else if (status.complete) {
            statusMessage.textContent = 'Backup complete!';
        } else if (processed > 0) {
             statusMessage.textContent = 'Backup in progress...';
        } else {
             statusMessage.textContent = 'Initializing...';
        }


        currentFileSpan.textContent = status.current_file || '-';
        processedFilesSpan.textContent = processed;
        totalFilesSpan.textContent = total;
        processedSizeSpan.textContent = formatBytes(status.bytes_processed || 0);
        totalSizeSpan.textContent = formatBytes(status.bytes_total || 0);
        timeRemainingSpan.textContent = status.est_time_remaining || (processed > 0 ? 'Calculating...' : '-');
    }


    // --- Load Initial Config ---
    function loadConfig() {
        fetch('/get-config')
            .then(r => r.ok ? r.json() : Promise.reject('Failed to load config'))
            .then(config => {
                sourceFolderInput.value = config.source || '';

                // Clear existing destinations and add from config
                destinationsContainer.innerHTML = ''; // Clear first
                if (config.destinations && config.destinations.length > 0) {
                    config.destinations.forEach(dest => addDestinationRow(dest));
                } else {
                    addDestinationRow(); // Add one empty row if no destinations saved
                }

                // Set naming options from config
                if (config.append_location === false) { // Explicitly false
                    if (config.folder_suffix) {
                        useSuffixRadio.checked = true;
                        folderSuffixInput.value = config.folder_suffix;
                    } else {
                        dateOnlyRadio.checked = true;
                    }
                } else { // Default or explicitly true
                    appendLocationRadio.checked = true;
                }
                handleNamingOptionChange(); // Update suffix input state based on loaded config

            })
            .catch(err => {
                console.error('Could not load config:', err);
                // Add a default destination row even if config fails
                if (destinationsContainer.children.length === 0) {
                    addDestinationRow();
                }
                handleNamingOptionChange(); // Ensure suffix disabled by default
            });
    }

    // Initial load
    loadConfig();

});'''

    with open(os.path.join(web_dir, 'scripts.js'), 'w', encoding='utf-8') as f:
        f.write(scripts_js_content)

    print("Web files updated/created in 'web' directory.")


# --- CLI Mode Functions ---

def prompt_for_directory(prompt_text, must_exist=True):
    """Prompts user for a directory path and validates it."""
    while True:
        path_str = input(f"{prompt_text}: ").strip()
        if not path_str:
            print("Path cannot be empty.")
            continue
        path = Path(path_str).resolve() # Resolve to absolute path
        if must_exist:
            if path.is_dir():
                return str(path)
            else:
                print(f"Error: Directory not found or is not a directory: {path}")
        else:
            # For destinations, allow non-existent if parent exists?
            # For simplicity, let's require destinations to exist for now.
            # If you want to allow creation, check path.parent.is_dir()
             if path.is_dir():
                 return str(path)
             else:
                 print(f"Error: Directory not found or is not a directory: {path}")
                 print("(Please create destination directories before running)")


def run_cli():
    """Runs the photo backup tool in Command Line Interface mode."""
    print("--- Photo Backup Tool (CLI Mode) ---")
    config = load_config()
    backup = PhotoBackup(cli_mode=True) # <-- Instantiate with cli_mode=True

    # --- Source Directory ---
    use_existing_source = False
    if config.get("source") and Path(config["source"]).is_dir():
        print(f"\nLast used source: {config['source']}")
        if input("Use this source directory? (Y/n): ").strip().lower() != 'n':
            backup.source_dir = config["source"]
            use_existing_source = True

    if not use_existing_source:
        backup.source_dir = prompt_for_directory("Enter SOURCE directory path", must_exist=True)
        config["source"] = backup.source_dir # Update config

    # --- Destination Directories ---
    use_existing_dest = False
    if config.get("destinations") and isinstance(config["destinations"], list) and config["destinations"]:
        valid_existing_dests = [d for d in config["destinations"] if Path(d).is_dir()]
        if valid_existing_dests:
            print("\nLast used destination(s):")
            for d in valid_existing_dests:
                print(f"- {d}")
            if input("Use these destination directories? (Y/n): ").strip().lower() != 'n':
                 backup.destination_dirs = valid_existing_dests
                 use_existing_dest = True

    if not use_existing_dest:
        backup.destination_dirs = []
        while True:
            dest_prompt = f"Enter DESTINATION directory {len(backup.destination_dirs) + 1} path"
            if backup.destination_dirs:
                 dest_prompt += " (or press Enter to finish)"

            path_str = input(f"{dest_prompt}: ").strip()
            if not path_str and backup.destination_dirs:
                break # Finished adding destinations
            elif not path_str:
                 print("Please add at least one destination directory.")
                 continue

            dest_path = Path(path_str).resolve()
            if dest_path.is_dir():
                 dest_str = str(dest_path)
                 if dest_str == backup.source_dir:
                      print("Error: Destination cannot be the same as the source.")
                 elif dest_str in backup.destination_dirs:
                      print("Error: Destination already added.")
                 else:
                      backup.destination_dirs.append(dest_str)
            else:
                 print(f"Error: Directory not found or is not a directory: {dest_path}")
                 print("(Please create destination directories before running)")

        if not backup.destination_dirs:
             print("No valid destination directories added. Exiting.")
             sys.exit(1)
        config["destinations"] = backup.destination_dirs # Update config


    # --- Folder Naming ---
    print("\nFolder Naming Options:")
    print(" 1. Date + Location (Best default, needs internet/GPS for location name)")
    print(" 2. Date + Custom Suffix (You provide the text after the date)")
    print(" 3. Date Only")

    # Load default from config if valid, otherwise default to 1
    default_choice = "1"
    if config.get("append_location") is False:
         if config.get("folder_suffix"):
             default_choice = "2"
         else:
             default_choice = "3"

    while True:
        choice = input(f"Enter choice ({default_choice}): ").strip() or default_choice
        if choice == '1':
            backup.append_location = True
            backup.folder_suffix = ""
            if not is_connected():
                 print("Warning: No internet connection detected. Location names may be less precise or 'Unknown'.")
            break
        elif choice == '2':
            backup.append_location = False
            while True:
                suffix = input("Enter custom suffix: ").strip()
                if suffix:
                    # Basic sanitization (replace common problematic chars) - more robust needed if complex names allowed
                    # safe_suffix = suffix.replace('/', '-').replace('\\', '-').replace(':', '-')
                    backup.folder_suffix = suffix # Store user input directly, sanitization happens in process_image
                    break
                else:
                    print("Suffix cannot be empty.")
            break
        elif choice == '3':
            backup.append_location = False
            backup.folder_suffix = ""
            break
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

    config["append_location"] = backup.append_location
    config["folder_suffix"] = backup.folder_suffix


    # --- Save Config and Start Backup ---
    print("\nConfiguration:")
    print(f" Source: {backup.source_dir}")
    print(f" Destinations: {', '.join(backup.destination_dirs)}")
    folder_mode_desc = "Date + Location" if backup.append_location else (f"Date + Suffix '{backup.folder_suffix}'" if backup.folder_suffix else "Date Only")
    print(f" Folder Naming: {folder_mode_desc}")

    if input("\nProceed with backup using this configuration? (Y/n): ").strip().lower() == 'n':
        print("Backup cancelled.")
        sys.exit(0)

    print("Saving configuration...")
    save_config(config)

    print("-" * 30)
    # Run the backup synchronously in the main thread for CLI
    backup.backup_images()
    print("-" * 30)
    # Final status is printed by the status_updater's finally block


# --- Main Execution ---

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Photo Backup Tool - Copies photos to destination folders, organizing by date and optional location/suffix.")
    parser.add_argument('--ui', action='store_true', help="Launch the web browser User Interface instead of running in CLI mode.")
    args = parser.parse_args()

    # --- Run Mode ---
    if args.ui:
        # --- UI Mode ---
        print("Starting Photo Backup Tool in UI mode...")
        # Create web files if they don't exist or need update
        create_web_files()

        # Start server
        server = PhotoBackupServer()
        try:
            port = server.start_server() # Handles printing messages and opening browser

            print("Press Ctrl+C in this terminal to stop the server.")
            # Keep the main thread alive while the server runs in its thread
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCtrl+C received.")
        except Exception as e:
            print(f"\nAn error occurred during UI server execution: {e}", file=sys.stderr)
        finally:
            server.stop_server()
            print("Photo Backup Tool UI finished.")

    else:
        # --- CLI Mode ---
        try:
            run_cli()
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
        except Exception as e:
            print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc() # Print full traceback for debugging CLI errors
        finally:
            print("Photo Backup Tool CLI finished.")


if __name__ == "__main__":
    # Ensure script directory is used for relative paths if needed
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()