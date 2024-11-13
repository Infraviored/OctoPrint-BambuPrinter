#!/usr/bin/env python3

"""
Script to list 3MF files from a Bambu printer's SD card.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
import sys
from pathlib import Path
from zipfile import ZipFile
import tempfile
import os 
from PIL import Image
import io
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add the parent directory to the Python path
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent.parent
sys.path.insert(0, str(project_root))

# Now we can import our local modules
from octoprint_bambu_printer.printer.file_system.ftps_client import IoTFTPSClient, IoTFTPSConnection
from octoprint_bambu_printer.printer.file_system.remote_sd_card_file_list import RemoteSDCardFileList


@dataclass
class MockSettings:
    """Mock settings class to simulate OctoPrint settings"""

    _settings: Dict[str, Any]

    def get(self, key):
        """Simulate OctoPrint's settings.get() method"""
        if isinstance(key, list):
            return self._settings[key[0]]
        return self._settings[key]


def create_settings(host: str, access_code: str) -> MockSettings:
    """Create a settings object with the required configuration"""
    return MockSettings(
        {
            "host": host,
            "access_code": access_code,
            "bambu_connection_type": "lan",  # Required for proper connection
            "use_local_storage": False,
        }
    )


def extract_thumbnails(ftp: IoTFTPSConnection, remote_path: str) -> list[Image.Image]:
    """
    Extract thumbnails from a 3MF file using a temporary file.
    
    Args:
        ftp: FTPS connection
        remote_path: Path to the 3MF file on the printer
        
    Returns:
        List of PIL Image objects
    """
    with tempfile.NamedTemporaryFile(suffix='.3mf', delete=True) as temp_file:
        # Download the 3MF file to a temporary location
        ftp.download_file(remote_path, temp_file.name)
        
        # Open as ZIP archive
        thumbnails = []
        try:
            with ZipFile(temp_file.name) as zip_file:
                # Look for thumbnail files
                for filename in zip_file.namelist():
                    if ('thumbnail' in filename.lower() and 
                        filename.lower().endswith(('.png', '.jpg', '.jpeg'))):
                        with zip_file.open(filename) as image_file:
                            img = Image.open(io.BytesIO(image_file.read()))
                            thumbnails.append(img)
        except Exception as e:
            print(f"  └── Error processing ZIP: {str(e)}")
            
        return thumbnails


def list_3mf_files(host: str, access_code: str) -> None:
    """List and process 3MF files with timing metrics"""
    settings = create_settings(host, access_code)
    file_list = RemoteSDCardFileList(settings)

    total_start = time.time()
    try:
        with file_list.get_ftps_client() as ftp:
            list_start = time.time()
            files = file_list.list_files(folder="/", extensions=".3mf", ftp=ftp)
            list_time = time.time() - list_start
            
            logger.info(f"Found {len(files)} 3MF files in {list_time:.2f}s")
            
            for file in files:
                logger.info(f"Processing: {file.file_name}")
                try:
                    extract_required_files(ftp, file.path)
                except Exception as e:
                    logger.error(f"Failed to process {file.file_name}: {str(e)}")

    except Exception as e:
        logger.error(f"Connection error: {str(e)}")
    
    total_time = time.time() - total_start
    logger.info(f"Total operation completed in {total_time:.2f}s")


def examine_3mf_structure(ftp: IoTFTPSConnection, remote_path: str) -> None:
    """
    Download and examine the contents of a single 3MF file, extracting thumbnails.
    
    Args:
        ftp: FTPS connection
        remote_path: Path to the 3MF file on the printer
    """
    # Create thumbnails directory in the script's location
    thumbnails_dir = os.path.join(os.path.dirname(__file__), "thumbnails")
    os.makedirs(thumbnails_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(suffix='.3mf', delete=True) as temp_file:
        print(f"Downloading {remote_path} to {temp_file.name}...")
        ftp.download_file(remote_path, temp_file.name)
        
        print("\nExamining 3MF structure and extracting thumbnails:")
        print("-" * 60)
        try:
            with ZipFile(temp_file.name) as zip_file:
                # List all files and extract PNGs from Metadata/
                for info in zip_file.filelist:
                    print(f"File: {info.filename}")
                    print(f"  Size: {info.file_size:,} bytes")
                    
                    # Extract if it's a PNG in Metadata/
                    if info.filename.startswith("Metadata/") and info.filename.endswith(".png"):
                        # Get just the filename part for saving
                        png_name = os.path.basename(info.filename)
                        save_path = os.path.join(thumbnails_dir, png_name)
                        
                        # Extract the image
                        with zip_file.open(info.filename) as image_file:
                            with open(save_path, 'wb') as f:
                                f.write(image_file.read())
                        print(f"  └── Extracted to: {save_path}")
                    print()
                
        except Exception as e:
            print(f"Error examining ZIP: {str(e)}")


def list_printer_filesystem(host: str, access_code: str) -> None:
    """
    List the entire file system structure of the printer.

    Args:
        host: Printer's IP address
        access_code: Printer's access code
    """
    settings = create_settings(host, access_code)
    file_list = RemoteSDCardFileList(settings)

    def print_directory_tree(ftp: IoTFTPSConnection, path: str = "/", level: int = 0) -> None:
        indent = "  │   " * (level - 1) + "  ├── " if level > 0 else ""
        try:
            # List all items in current directory
            items = ftp.list_files(path, None)
            
            # Sort items (directories first)
            dirs = []
            files = []
            for item in items:
                full_path = f"{path.rstrip('/')}/{item.name}".replace("//", "/")
                try:
                    # Try to get file size - if it fails, it's probably a directory
                    size = ftp.get_file_size(full_path)
                    files.append((item, size))
                except:
                    dirs.append(item)
            
            # Print directories
            for i, dir_path in enumerate(sorted(dirs)):
                is_last = (i == len(dirs) - 1) and not files
                dir_indent = indent[:-4] + "  └── " if is_last else indent
                print(f"{dir_indent}{dir_path.name}/")
                # Recursively process subdirectory
                next_path = f"{path.rstrip('/')}/{dir_path.name}".replace("//", "/")
                print_directory_tree(ftp, next_path, level + 1)
            
            # Print files
            for i, (file_path, size) in enumerate(sorted(files)):
                is_last = i == len(files) - 1
                file_indent = indent[:-4] + "  └── " if is_last else indent
                full_path = f"{path.rstrip('/')}/{file_path.name}".replace("//", "/")
                date = ftp.get_file_date(full_path)
                print(f"{file_indent}{file_path.name} ({size:,} bytes, {date})")
                
        except Exception as e:
            print(f"{indent}Error reading {path}: {str(e)}")

    try:
        with file_list.get_ftps_client() as ftp:
            print("\nScanning printer filesystem...")
            print("=" * 60)
            print_directory_tree(ftp)
            print("=" * 60)

    except Exception as e:
        print(f"\nError: {str(e)}")
        print("\nPlease verify:")
        print("1. The printer is powered on")
        print("2. The IP address is correct")
        print("3. The access code is correct")
        print("4. You're on the same network as the printer")


def extract_required_files(ftp: IoTFTPSConnection, remote_path: str) -> None:
    """Extract specific files from 3MF archive with timing metrics"""
    required_files = {
        "Metadata/plate_1.png",
        "Metadata/top_1.png",
        "Metadata/model_settings.config"
    }
    
    base_name = os.path.splitext(os.path.basename(remote_path))[0]
    output_dir = os.path.join(os.path.dirname(__file__), base_name)
    os.makedirs(output_dir, exist_ok=True)
    
    download_start = time.time()
    with tempfile.NamedTemporaryFile(suffix='.3mf', delete=True) as temp_file:
        ftp.download_file(remote_path, temp_file.name)
        download_time = time.time() - download_start
        file_size = os.path.getsize(temp_file.name)
        logger.info(f"Downloaded {remote_path} ({file_size/1024/1024:.1f} MB) in {download_time:.2f}s")
        
        extract_start = time.time()
        with ZipFile(temp_file.name, 'r') as zip_file:
            # Get info about all files without reading contents
            file_info = {info.filename: info for info in zip_file.filelist}
            
            # Calculate total size of required files
            total_size = sum(file_info[f].file_size for f in required_files if f in file_info)
            logger.info(f"Extracting {len(required_files)} files ({total_size/1024:.1f} KB)")
            
            # Extract only required files
            for filename in required_files:
                if filename in file_info:
                    save_path = os.path.join(output_dir, os.path.basename(filename))
                    with zip_file.open(filename) as src, open(save_path, 'wb') as dest:
                        dest.write(src.read())
        
        extract_time = time.time() - extract_start
        logger.info(f"Extraction completed in {extract_time:.2f}s")
        logger.info(f"Total processing time: {(download_time + extract_time):.2f}s")


def main():
    """Main entry point with configuration validation"""
    PRINTER_IP = "192.168.178.70"
    ACCESS_CODE = "33055062"

    if PRINTER_IP == "192.168.1.100" or ACCESS_CODE == "12345678":
        logger.error("Please configure proper printer IP and access code!")
        return

    logger.info(f"Connecting to printer at {PRINTER_IP}")
    list_3mf_files(PRINTER_IP, ACCESS_CODE)


if __name__ == "__main__":
    main()
