"""
HEC Monolith Downloader

Replicates dssrip2's monolith installation approach.
Downloads HEC Monolith JARs and native libraries from HEC Nexus repository.

Based on: https://github.com/mkoohafkan/dssrip2
"""

import os
import sys
import platform
import hashlib
import zipfile
from pathlib import Path
from typing import List, Dict, Optional
import requests
from tqdm import tqdm


class HecMonolithDownloader:
    """
    Download and manage HEC Monolith libraries.

    Replicates dssrip2's requirements.yaml and download logic.
    """

    # HEC Nexus repository
    NEXUS_BASE = "https://www.hec.usace.army.mil/nexus/repository/maven-public"
    MAVEN_BASE = "https://repo.maven.apache.org/maven2"

    # Requirements (from dssrip2's requirements.yaml)
    COMMON_JARS = [
        {"artifactId": "hec-monolith", "group": "mil.army.usace.hec", "version": "3.3.27"},
        {"artifactId": "hec-monolith-compat", "group": "mil.army.usace.hec", "version": "3.3.27"},
        {"artifactId": "hec-nucleus-data", "group": "mil.army.usace.hec", "version": "2.0.1"},
        {"artifactId": "hec-nucleus-metadata", "group": "mil.army.usace.hec", "version": "2.0.1"},
        {"artifactId": "hecnf", "group": "mil.army.usace.hec.hecnf", "version": "7.2.0"},
        {"artifactId": "flogger", "group": "com.google.flogger", "version": "0.5.1", "source": "maven"},
        {"artifactId": "flogger-system-backend", "group": "com.google.flogger", "version": "0.5.1", "source": "maven"},
    ]

    # Platform-specific native libraries
    NATIVE_LIBS = {
        "Windows": {"artifactId": "javaHeclib", "group": "mil.army.usace.hec",
                    "version": "7-IU-8-win-x86_64", "extension": "zip"},
        "Linux": {"artifactId": "javaHeclib", "group": "mil.army.usace.hec",
                  "version": "7-IU-8-linux-x86_64", "extension": "zip"},
        "Darwin": {"artifactId": "javaHeclib", "group": "mil.army.usace.hec",
                   "version": "7-IU-8-macOS-x86_64", "extension": "zip"},
    }

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize downloader.

        Args:
            cache_dir: Directory to cache downloads.
                      Defaults to ~/.ras-commander/dss/
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".ras-commander" / "dss"

        self.cache_dir = Path(cache_dir)
        self.jar_dir = self.cache_dir / "jar"
        self.lib_dir = self.cache_dir / "lib"

        # Create directories
        self.jar_dir.mkdir(parents=True, exist_ok=True)
        self.lib_dir.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        """Check if HEC Monolith is already installed."""
        # Check for key JARs
        required_jars = ["hec-monolith", "hec-nucleus-data"]
        for jar_name in required_jars:
            if not list(self.jar_dir.glob(f"{jar_name}*.jar")):
                return False

        # Check for native library
        platform_name = platform.system()
        if platform_name == "Windows":
            lib_file = "javaHeclib.dll"
        elif platform_name == "Linux":
            lib_file = "libjavaHeclib.so"
        elif platform_name == "Darwin":
            lib_file = "libjavaHeclib.dylib"
        else:
            return False

        return (self.lib_dir / lib_file).exists()

    def get_download_url(self, artifact: Dict, source: str = "nexus") -> str:
        """
        Construct Maven download URL.

        Args:
            artifact: Artifact specification dict
            source: "nexus" or "maven"

        Returns:
            Download URL
        """
        group = artifact["group"].replace(".", "/")
        artifact_id = artifact["artifactId"]
        version = artifact["version"]
        extension = artifact.get("extension", "jar")

        filename = f"{artifact_id}-{version}.{extension}"

        if source == "maven":
            base = self.MAVEN_BASE
        else:
            base = self.NEXUS_BASE

        url = f"{base}/{group}/{artifact_id}/{version}/{filename}"
        return url

    def download_file(self, url: str, dest: Path, description: str = "") -> Path:
        """
        Download file with progress bar.

        Args:
            url: URL to download
            dest: Destination file path
            description: Description for progress bar

        Returns:
            Path to downloaded file
        """
        if dest.exists():
            print(f"  Using cached: {dest.name}")
            return dest

        print(f"  Downloading: {description or dest.name}")

        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))

        with open(dest, 'wb') as f:
            with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    pbar.update(len(chunk))

        return dest

    def verify_sha1(self, filepath: Path, expected_sha1: Optional[str] = None) -> bool:
        """
        Verify SHA1 checksum of file.

        Args:
            filepath: File to verify
            expected_sha1: Expected SHA1 hash (if None, tries to download .sha1 file)

        Returns:
            True if checksum matches
        """
        if expected_sha1 is None:
            # Try to download .sha1 file
            return True  # Skip verification if no checksum available

        sha1 = hashlib.sha1()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                sha1.update(chunk)

        computed = sha1.hexdigest()
        return computed == expected_sha1

    def download_jars(self):
        """Download all required JAR files."""
        print("\nDownloading HEC Monolith JAR files...")

        for artifact in self.COMMON_JARS:
            source = artifact.get("source", "nexus")
            url = self.get_download_url(artifact, source)
            filename = f"{artifact['artifactId']}-{artifact['version']}.jar"
            dest = self.jar_dir / filename

            self.download_file(url, dest, artifact['artifactId'])

    def download_native_library(self):
        """Download platform-specific native library."""
        platform_name = platform.system()

        if platform_name not in self.NATIVE_LIBS:
            raise RuntimeError(f"Unsupported platform: {platform_name}")

        print(f"\nDownloading native library for {platform_name}...")

        artifact = self.NATIVE_LIBS[platform_name]
        url = self.get_download_url(artifact)
        filename = f"{artifact['artifactId']}-{artifact['version']}.zip"
        dest = self.lib_dir / filename

        # Download ZIP
        self.download_file(url, dest, f"Native library ({platform_name})")

        # Extract ZIP
        print(f"  Extracting native library...")
        with zipfile.ZipFile(dest, 'r') as zip_ref:
            zip_ref.extractall(self.lib_dir)

        # Remove ZIP file
        dest.unlink()

        print(f"  [OK] Native library installed")

    def install(self, force: bool = False):
        """
        Download and install HEC Monolith.

        Args:
            force: Force re-download even if already installed
        """
        if self.is_installed() and not force:
            print("HEC Monolith already installed")
            return

        if force:
            print("Forcing re-download of HEC Monolith...")

        print("="*80)
        print("Installing HEC Monolith Libraries")
        print("="*80)
        print(f"Install location: {self.cache_dir}")

        # Download JARs
        self.download_jars()

        # Download native library
        self.download_native_library()

        print("\n" + "="*80)
        print("[SUCCESS] HEC Monolith installation complete!")
        print("="*80)

    def get_classpath(self) -> List[str]:
        """
        Get list of JAR paths for JVM classpath.

        Returns:
            List of absolute JAR file paths
        """
        if not self.is_installed():
            raise RuntimeError("HEC Monolith not installed. Call install() first.")

        jar_files = list(self.jar_dir.glob("*.jar"))
        return [str(jar.resolve()) for jar in sorted(jar_files)]

    def get_library_path(self) -> str:
        """
        Get path to native library directory.

        Returns:
            Absolute path to lib directory containing native libraries
        """
        if not self.is_installed():
            raise RuntimeError("HEC Monolith not installed. Call install() first.")

        return str(self.lib_dir.resolve())

    def get_info(self) -> Dict:
        """
        Get information about installation.

        Returns:
            Dict with installation details
        """
        jars = list(self.jar_dir.glob("*.jar"))
        libs = list(self.lib_dir.glob("*"))

        total_size = sum(f.stat().st_size for f in jars + libs)

        return {
            "installed": self.is_installed(),
            "cache_dir": str(self.cache_dir),
            "num_jars": len(jars),
            "jar_files": [j.name for j in sorted(jars)],
            "lib_files": [l.name for l in sorted(libs)],
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "platform": platform.system(),
        }


if __name__ == "__main__":
    """Test installation"""
    downloader = HecMonolithDownloader()

    print("HEC Monolith Downloader Test")
    print("="*80)

    # Check current status
    info = downloader.get_info()
    print(f"\nInstalled: {info['installed']}")
    print(f"Cache dir: {info['cache_dir']}")

    if not info['installed']:
        # Install
        downloader.install()

        # Show info
        info = downloader.get_info()
        print(f"\nInstallation complete:")
        print(f"  JARs: {info['num_jars']}")
        print(f"  Total size: {info['total_size_mb']} MB")
        print(f"\nClasspath:")
        for jar in downloader.get_classpath():
            print(f"  - {Path(jar).name}")
        print(f"\nLibrary path: {downloader.get_library_path()}")
    else:
        print("\nAlready installed!")
        print(f"  JARs: {info['num_jars']}")
        print(f"  Total size: {info['total_size_mb']} MB")
