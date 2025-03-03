import exifread
import reverse_geocoder as rg
import sys


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


def get_exif_data(image_path):
    """Extract EXIF data from image using ExifRead"""
    try:
        with open(image_path, 'rb') as f:
            tags = exifread.process_file(f)
        return tags
    except Exception as e:
        print(f"Error extracting EXIF data: {e}")
    return {}

def get_gps_data(exif_data):
    """Extract GPS data from EXIF"""
    gps_info = {}
    if 'GPS GPSLatitude' in exif_data and 'GPS GPSLongitude' in exif_data:
        gps_info['GPSLatitude'] = exif_data['GPS GPSLatitude'].values
        gps_info['GPSLatitudeRef'] = exif_data.get('GPS GPSLatitudeRef', 'N')
        gps_info['GPSLongitude'] = exif_data['GPS GPSLongitude'].values
        gps_info['GPSLongitudeRef'] = exif_data.get('GPS GPSLongitudeRef', 'E')
    return gps_info

def get_coordinates(gps_info):
    """Convert GPS coordinates from EXIF to decimal degrees"""
    if not gps_info or 'GPSLatitude' not in gps_info or 'GPSLongitude' not in gps_info:
        return None

    lat = gps_info['GPSLatitude']
    lat_ref = gps_info.get('GPSLatitudeRef', 'N')
    lon = gps_info['GPSLongitude']
    lon_ref = gps_info.get('GPSLongitudeRef', 'E')

    lat = float(lat[0].num) / float(lat[0].den) + \
          float(lat[1].num) / (60 * float(lat[1].den)) + \
          float(lat[2].num) / (3600 * float(lat[2].den))
    if lat_ref == 'S':
        lat = -lat

    lon = float(lon[0].num) / float(lon[0].den) + \
          float(lon[1].num) / (60 * float(lon[1].den)) + \
          float(lon[2].num) / (3600 * float(lon[2].den))
    if lon_ref == 'W':
        lon = -lon

    return (lat, lon)

def get_location_name(coords):
    """Get location name from GPS coordinates"""
    try:
        if not coords:
            return "Unknown"

        result = rg.search(coords)[0]
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
            print(location)
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

    except Exception as e:
        print(f"Error in reverse geocoding: {e}")
        return "Unknown"

def main(image_path):
    exif_data = get_exif_data(image_path)
    gps_info = get_gps_data(exif_data)
    coords = get_coordinates(gps_info)

    print(f"GPS Coordinates: {coords}")
    if coords:
        location = get_location_name(coords)
        print(f"Location: {location}")
    else:
        print("No GPS data found.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <image_path>")
    else:
        main(sys.argv[1])
