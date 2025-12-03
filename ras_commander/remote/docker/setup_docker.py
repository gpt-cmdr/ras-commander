#!/usr/bin/env python3
"""
HEC-RAS Docker Image Setup Script

This script downloads HEC-RAS Linux binaries and builds Docker images for
running HEC-RAS simulations in containers.

Supported Versions:
    - 5.07: Basic 1D/2D support (oldest)
    - 6.10: Improved 2D performance
    - 6.5:  Enhanced features
    - 6.6:  Current stable release
    - 6.7:  Beta with latest features (binaries included with Windows installer)

Usage:
    python setup_docker.py --version 6.6
    python setup_docker.py --version 6.7 --ras-install "C:\\Program Files (x86)\\HEC\\HEC-RAS\\6.7 Beta 5"
    python setup_docker.py --version all
    python setup_docker.py --list

Requirements:
    - Docker Desktop installed and running
    - Internet connection (for downloading binaries)
    - ~3GB disk space per version
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError

# Version configuration
VERSIONS = {
    "5.07": {
        "url": "https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_507_linux.zip",
        "base_image": "centos:7",
        "bin_path": "bin",
        "libs_path": "libs",
        "notes": "Oldest supported version, CentOS 7 base"
    },
    "6.10": {
        "url": "https://www.hec.usace.army.mil/software/hec-ras/downloads/HEC-RAS_610_Linux.zip",
        "base_image": "rockylinux:8",
        "bin_path": "bin",
        "libs_path": "libs",
        "notes": "Rocky Linux 8 base"
    },
    "6.5": {
        "url": "https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v65.zip",
        "base_image": "rockylinux:8",
        "bin_path": "bin",
        "libs_path": "libs",
        "notes": "Rocky Linux 8 base"
    },
    "6.6": {
        "url": "https://www.hec.usace.army.mil/software/hec-ras/downloads/Linux_RAS_v66.zip",
        "base_image": "rockylinux:8",
        "bin_path": "bin",
        "libs_path": "libs",
        "notes": "Current stable release, Rocky Linux 8 base"
    },
    "6.7": {
        "url": None,  # Included with Windows installer
        "base_image": "rockylinux:8",
        "bin_path": "",  # Executables in Linux/ root
        "libs_path": "libs",
        "notes": "Beta version - extract from Windows installer",
        "windows_installer": "https://github.com/HydrologicEngineeringCenter/hec-downloads/releases/download/1.0.42/HEC-RAS_67_Beta_5_with_Linux_Setup.exe"
    }
}


def print_header(msg: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f" {msg}")
    print(f"{'='*60}")


def print_step(msg: str):
    """Print a step message."""
    print(f"\n>>> {msg}")


def check_docker():
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print("ERROR: Docker daemon is not running.")
            print("Please start Docker Desktop and try again.")
            return False
        return True
    except FileNotFoundError:
        print("ERROR: Docker is not installed.")
        print("Please install Docker Desktop from: https://www.docker.com/products/docker-desktop")
        return False
    except subprocess.TimeoutExpired:
        print("ERROR: Docker command timed out.")
        return False


def download_file(url: str, dest: Path, desc: str = "Downloading") -> bool:
    """Download a file with progress indication."""
    print_step(f"{desc}: {url}")

    def progress_hook(count, block_size, total_size):
        percent = int(count * block_size * 100 / total_size) if total_size > 0 else 0
        print(f"\r  Progress: {percent}%", end="", flush=True)

    try:
        urlretrieve(url, dest, reporthook=progress_hook)
        print()  # Newline after progress
        return True
    except URLError as e:
        print(f"\nERROR: Failed to download: {e}")
        return False
    except Exception as e:
        print(f"\nERROR: {e}")
        return False


def extract_zip(zip_path: Path, extract_to: Path) -> bool:
    """Extract a zip file."""
    print_step(f"Extracting to {extract_to}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_to)
        return True
    except Exception as e:
        print(f"ERROR: Failed to extract: {e}")
        return False


def find_linux_binaries(extract_path: Path, version: str) -> Path:
    """Find the Linux binaries folder after extraction."""
    # Common patterns for extracted folders
    patterns = [
        f"Linux_RAS_v{version.replace('.', '')}",
        f"HEC-RAS_{version.replace('.', '')}_Linux",
        f"HEC-RAS_{version.replace('.', '')}_linux",
        "Linux",
        "linux",
    ]

    # Also check for nested directories
    for pattern in patterns:
        # Direct match
        direct = extract_path / pattern
        if direct.exists():
            return direct

        # One level nested
        for item in extract_path.iterdir():
            if item.is_dir():
                nested = item / pattern
                if nested.exists():
                    return nested
                # Check if this IS the folder
                if pattern.lower() in item.name.lower():
                    return item

    # Fallback: look for RasUnsteady executable
    for root, dirs, files in os.walk(extract_path):
        if "RasUnsteady" in files:
            return Path(root).parent if "bin" in root else Path(root)

    return extract_path


def setup_version_from_download(version: str, build_dir: Path) -> bool:
    """Download and setup a version from HEC website."""
    config = VERSIONS[version]

    if not config["url"]:
        print(f"ERROR: Version {version} does not have a direct download URL.")
        print("Use --ras-install to specify the Windows installation path.")
        return False

    # Create temp directory for download
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        zip_file = tmppath / f"hecras_{version}.zip"

        # Download
        if not download_file(config["url"], zip_file, f"Downloading HEC-RAS {version} Linux"):
            return False

        # Extract
        extract_dir = tmppath / "extracted"
        extract_dir.mkdir()
        if not extract_zip(zip_file, extract_dir):
            return False

        # Find Linux binaries
        linux_dir = find_linux_binaries(extract_dir, version)
        print(f"  Found Linux binaries at: {linux_dir}")

        # Copy to build directory
        ras_dir = build_dir / "ras_linux"
        if ras_dir.exists():
            shutil.rmtree(ras_dir)

        shutil.copytree(linux_dir, ras_dir)
        print(f"  Copied to: {ras_dir}")

    return True


def setup_version_from_install(version: str, install_path: Path, build_dir: Path) -> bool:
    """Setup a version from existing Windows installation."""
    linux_dir = install_path / "Linux"

    if not linux_dir.exists():
        print(f"ERROR: Linux folder not found at: {linux_dir}")
        print("Make sure you have the 'with Linux' version installed.")
        return False

    # Verify required files exist
    required = ["RasUnsteady"]
    for exe in required:
        # Check in root and bin subfolder
        if not (linux_dir / exe).exists() and not (linux_dir / "bin" / exe).exists():
            print(f"ERROR: Required file not found: {exe}")
            return False

    # Copy to build directory
    ras_dir = build_dir / "ras_linux"
    if ras_dir.exists():
        shutil.rmtree(ras_dir)

    print_step(f"Copying Linux binaries from {linux_dir}")
    shutil.copytree(linux_dir, ras_dir)
    print(f"  Copied to: {ras_dir}")

    return True


def generate_dockerfile(version: str, build_dir: Path) -> bool:
    """Generate a Dockerfile for the specified version."""
    config = VERSIONS[version]

    # Determine paths based on version structure
    ras_dir = build_dir / "ras_linux"

    # Check structure (executables in root vs bin/)
    if (ras_dir / "RasUnsteady").exists():
        bin_copy = "COPY ras_linux/RasUnsteady ras_linux/RasGeomPreprocess ras_linux/RasSteady /app/bin/"
        libs_copy = "COPY ras_linux/libs/ /app/libs/"
    elif (ras_dir / "bin" / "RasUnsteady").exists():
        bin_copy = "COPY ras_linux/bin/ /app/bin/"
        libs_copy = "COPY ras_linux/libs/ /app/libs/"
    else:
        print(f"ERROR: Cannot determine binary structure for version {version}")
        return False

    dockerfile_content = f'''# HEC-RAS {version} Linux Docker Container
# Auto-generated by setup_docker.py

FROM {config["base_image"]}

# Install system dependencies
RUN {"yum" if "centos" in config["base_image"] or "rocky" in config["base_image"] else "apt-get"} update -y && \\
    {"yum" if "centos" in config["base_image"] or "rocky" in config["base_image"] else "apt-get"} install -y \\
    findutils \\
    glibc \\
    libgcc \\
    libstdc++ \\
    && {"yum clean all" if "centos" in config["base_image"] or "rocky" in config["base_image"] else "apt-get clean"}

# Create working directory
WORKDIR /app

# Copy HEC-RAS Linux binaries
{bin_copy}
{libs_copy}

# Copy execution script
COPY scripts/run_ras.sh /app/scripts/core_execution/
RUN sed -i 's/\\r$//' /app/scripts/core_execution/run_ras.sh && \\
    chmod +x /app/scripts/core_execution/run_ras.sh && \\
    chmod +x /app/bin/*

# Set library path environment
ENV LD_LIBRARY_PATH="/app/libs:/app/libs/mkl:/app/libs/rhel_8"
ENV PATH="/app/bin:$PATH"

# Create working directories
RUN mkdir -p /app/input /app/output /app/work

# Create non-root user for security
RUN useradd -m -u 1000 rasuser && \\
    chown -R rasuser:rasuser /app

# Set default timeout (8 hours)
ENV MAX_RUNTIME_MINUTES=480

VOLUME ["/app/input", "/app/output"]

# No default command - controlled by DockerWorker
'''

    dockerfile_path = build_dir / "Dockerfile"
    print_step(f"Generating Dockerfile: {dockerfile_path}")

    with open(dockerfile_path, 'w', newline='\n') as f:
        f.write(dockerfile_content)

    return True


def copy_scripts(build_dir: Path) -> bool:
    """Copy the run_ras.sh script to build directory."""
    scripts_dir = build_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    # Get the script from this module's directory
    module_dir = Path(__file__).parent
    src_script = module_dir / "scripts" / "run_ras.sh"

    if not src_script.exists():
        print(f"ERROR: run_ras.sh not found at {src_script}")
        return False

    dst_script = scripts_dir / "run_ras.sh"
    shutil.copy2(src_script, dst_script)
    print(f"  Copied run_ras.sh to {dst_script}")

    return True


def build_docker_image(version: str, build_dir: Path) -> bool:
    """Build the Docker image."""
    image_tag = f"hecras:{version.replace(' ', '_').lower()}"

    print_step(f"Building Docker image: {image_tag}")
    print(f"  Build context: {build_dir}")

    try:
        result = subprocess.run(
            ["docker", "build", "-t", image_tag, "."],
            cwd=build_dir,
            capture_output=False,  # Show output
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode != 0:
            print(f"ERROR: Docker build failed with exit code {result.returncode}")
            return False

        print(f"\nSUCCESS: Docker image built: {image_tag}")
        return True

    except subprocess.TimeoutExpired:
        print("ERROR: Docker build timed out")
        return False
    except Exception as e:
        print(f"ERROR: Docker build failed: {e}")
        return False


def list_versions():
    """List available versions and their status."""
    print_header("Available HEC-RAS Linux Versions")

    for version, config in VERSIONS.items():
        print(f"\n  Version {version}:")
        print(f"    Base Image: {config['base_image']}")
        print(f"    Notes: {config['notes']}")
        if config['url']:
            print(f"    Download: Direct from HEC")
        else:
            print(f"    Download: Extract from Windows installer")

    # Check which images are already built
    print("\n  Currently built images:")
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}", "--filter", "reference=hecras:*"],
            capture_output=True,
            text=True
        )
        images = result.stdout.strip().split('\n') if result.stdout.strip() else []
        if images and images[0]:
            for img in images:
                print(f"    - {img}")
        else:
            print("    (none)")
    except:
        print("    (unable to check - is Docker running?)")


def setup_version(version: str, ras_install: Path = None, keep_build: bool = False) -> bool:
    """Setup and build Docker image for a specific version."""
    print_header(f"Setting up HEC-RAS {version} Docker Image")

    if version not in VERSIONS:
        print(f"ERROR: Unknown version: {version}")
        print(f"Available versions: {', '.join(VERSIONS.keys())}")
        return False

    # Create build directory
    module_dir = Path(__file__).parent
    build_dir = module_dir / "build" / f"v{version.replace('.', '_')}"
    build_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Get binaries
        if ras_install:
            success = setup_version_from_install(version, ras_install, build_dir)
        else:
            success = setup_version_from_download(version, build_dir)

        if not success:
            return False

        # Copy scripts
        if not copy_scripts(build_dir):
            return False

        # Generate Dockerfile
        if not generate_dockerfile(version, build_dir):
            return False

        # Build image
        if not build_docker_image(version, build_dir):
            return False

        return True

    finally:
        # Cleanup build directory unless --keep-build specified
        if not keep_build and build_dir.exists():
            print_step("Cleaning up build directory...")
            shutil.rmtree(build_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Setup HEC-RAS Docker images for remote execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--version", "-v",
        choices=list(VERSIONS.keys()) + ["all"],
        help="HEC-RAS version to setup (or 'all' for all versions)"
    )

    parser.add_argument(
        "--ras-install",
        type=Path,
        help="Path to Windows HEC-RAS installation (for versions without direct download)"
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available versions and their status"
    )

    parser.add_argument(
        "--keep-build",
        action="store_true",
        help="Keep build directory after completion (for debugging)"
    )

    args = parser.parse_args()

    # Check Docker first
    if not args.list and not check_docker():
        sys.exit(1)

    if args.list:
        list_versions()
        return

    if not args.version:
        parser.print_help()
        print("\nERROR: --version is required")
        sys.exit(1)

    if args.version == "all":
        # Build all versions
        success_count = 0
        for version in VERSIONS.keys():
            if setup_version(version, args.ras_install, args.keep_build):
                success_count += 1

        print_header(f"Completed: {success_count}/{len(VERSIONS)} versions built")
        sys.exit(0 if success_count == len(VERSIONS) else 1)
    else:
        # Build single version
        success = setup_version(args.version, args.ras_install, args.keep_build)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
