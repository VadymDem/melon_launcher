import os
import subprocess
import platform
import requests
import tarfile
import zipfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class JavaInstallation:
    path: Path
    version: int
    vendor: str
    is_valid: bool = True
    error: str = ""


def parse_java_version(output: str) -> Optional[int]:
    """
    Extract the Java major version from `java -version` output.

    Java 8 and older report themselves with a legacy ``1.x`` scheme::

        openjdk version "1.8.0_402" 2022-01-18   ->  8
        openjdk version "17.0.8" 2023-07-18      -> 17
        openjdk version "21" 2023-09-19          -> 21

    Reading only the first number would report 1 for every Java 8 build and
    make a correctly installed runtime look like a version mismatch.
    """
    import re

    match = re.search(r'version\s+"([^"]+)"', output)
    if not match:
        return None

    raw = match.group(1).strip()

    # Legacy scheme: 1.8.0_402 / 1.7.0 / 1.6.0_45
    if raw.startswith("1."):
        legacy = re.match(r"1\.(\d+)", raw)
        return int(legacy.group(1)) if legacy else None

    # Modern scheme: 17.0.8 / 21 / 11.0.2
    modern = re.match(r"(\d+)", raw)
    return int(modern.group(1)) if modern else None


class JavaManager:
    """
    Manages Java Runtime: detection, validation, and downloading from Adoptium Temurin.
    """
    
    # Adoptium API endpoints
    ADOPTIUM_API = "https://api.adoptium.net/v3"
    ADOPTIUM_RELEASE_URL = "https://github.com/adoptium/temurin-build/releases/download"
    
    # Supported Java versions for Minecraft
    SUPPORTED_VERSIONS = [8, 11, 17, 21]
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.runtime_path = self.base_path / "runtime"
        self.runtime_path.mkdir(parents=True, exist_ok=True)

    def get_java_path(self, version: int) -> Path:
        """Get the expected path for a Java version."""
        return self.runtime_path / f"java-{version}" / "bin" / ("java.exe" if platform.system() == "Windows" else "java")

    def get_java_home(self, version: int) -> Path:
        """Get the Java home directory for a version."""
        return self.runtime_path / f"java-{version}"

    def check_java_installed(self, required_version: int) -> JavaInstallation:
        """
        Check if the required Java version is installed in our runtime directory.
        Returns JavaInstallation with validation result.
        """
        java_exe = self.get_java_path(required_version)
        java_home = self.get_java_home(required_version)
        
        if not java_exe.exists():
            return JavaInstallation(
                path=java_exe,
                version=required_version,
                vendor="unknown",
                is_valid=False,
                error=f"Java {required_version} not found at {java_exe}"
            )
        
        # Validate by running java -version
        try:
            result = subprocess.run(
                [str(java_exe), "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # java -version outputs to stderr
            version_output = result.stderr + result.stdout

            detected_version = parse_java_version(version_output)
            if detected_version is not None and detected_version != required_version:
                return JavaInstallation(
                    path=java_exe,
                    version=required_version,
                    vendor="unknown",
                    is_valid=False,
                    error=f"Version mismatch: expected {required_version}, found {detected_version}"
                )
            
            # Detect vendor
            vendor = "unknown"
            if "temurin" in version_output.lower() or "adoptium" in version_output.lower():
                vendor = "Temurin"
            elif "oracle" in version_output.lower():
                vendor = "Oracle"
            elif "openjdk" in version_output.lower():
                vendor = "OpenJDK"
            
            return JavaInstallation(
                path=java_exe,
                version=required_version,
                vendor=vendor,
                is_valid=True
            )
            
        except subprocess.TimeoutExpired:
            return JavaInstallation(
                path=java_exe,
                version=required_version,
                vendor="unknown",
                is_valid=False,
                error="java -version timed out"
            )
        except Exception as e:
            return JavaInstallation(
                path=java_exe,
                version=required_version,
                vendor="unknown",
                is_valid=False,
                error=f"Validation failed: {e}"
            )

    def find_system_java(self, required_version: int) -> Optional[JavaInstallation]:
        """Try to find a suitable Java installation in system PATH."""
        try:
            # Check if 'java' is in PATH
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            version_output = result.stderr + result.stdout

            detected_version = parse_java_version(version_output)
            if detected_version == required_version:
                java_path = Path(shutil.which("java")).resolve()
                vendor = "unknown"
                if "temurin" in version_output.lower():
                    vendor = "Temurin"
                elif "oracle" in version_output.lower():
                    vendor = "Oracle"
                elif "openjdk" in version_output.lower():
                    vendor = "OpenJDK"

                return JavaInstallation(
                    path=java_path,
                    version=required_version,
                    vendor=vendor,
                    is_valid=True
                )
        except Exception:
            pass
        return None

    def get_download_url(self, version: int, os_name: str = None, arch: str = None) -> Optional[str]:
        """
        Get the download URL for the specified Java version from Adoptium API.
        """
        if os_name is None:
            os_name = self._get_adoptium_os()
        if arch is None:
            arch = self._get_adoptium_arch()
        
        if version not in self.SUPPORTED_VERSIONS:
            return None
        
        try:
            # Query Adoptium API for latest release
            url = f"{self.ADOPTIUM_API}/assets/latest/{version}/hotspot"
            params = {
                "architecture": arch,
                "heap_size": "normal",
                "image_type": "jre",
                "os": os_name,
                "vendor": "eclipse"
            }
            
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                # Get the binary download link
                binary = data[0].get("binary", {})
                package = binary.get("package", {})
                download_link = package.get("link")
                if download_link:
                    return download_link
            
        except Exception as e:
            print(f"Failed to get download URL from Adoptium API: {e}")
        
        return None

    def _get_adoptium_os(self) -> str:
        system = platform.system().lower()
        if system == "windows":
            return "windows"
        elif system == "darwin":
            return "mac"
        elif system == "linux":
            return "linux"
        return "linux"

    def _get_adoptium_arch(self) -> str:
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return "x64"
        elif machine in ("aarch64", "arm64"):
            return "aarch64"
        elif machine in ("armv7l", "armv8"):
            return "arm"
        return "x64"

    def download_java(self, required_version: int, progress_callback=None) -> bool:
        """
        Download and extract Java JRE from Adoptium Temurin.
        progress_callback: function(bytes_downloaded, total_bytes)
        """
        if required_version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"Unsupported Java version: {required_version}")
        
        download_url = self.get_download_url(required_version)
        if not download_url:
            raise RuntimeError(f"Could not find download URL for Java {required_version}")
        
        java_home = self.get_java_home(required_version)
        java_home.mkdir(parents=True, exist_ok=True)
        
        # Determine archive format
        is_windows = platform.system() == "Windows"
        archive_suffix = ".zip" if is_windows else ".tar.gz"
        
        # Download to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=archive_suffix, delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)
        
        try:
            # Download with progress. The timeouts matter: (connect, read) fail
            # fast on an unreachable host instead of hanging the launcher.
            response = requests.get(
                download_url, stream=True, timeout=(15, 60)
            )
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            # Extract
            if progress_callback:
                progress_callback(total_size, total_size)  # Signal extraction start
            
            if is_windows:
                with zipfile.ZipFile(tmp_path, "r") as zf:
                    zf.extractall(java_home)
            else:
                with tarfile.open(tmp_path, "r:gz") as tf:
                    tf.extractall(java_home)
            
            # The extracted folder usually has a versioned name, find and flatten
            self._flatten_java_directory(java_home)
            
            # Verify installation
            install_check = self.check_java_installed(required_version)
            return install_check.is_valid
            
        finally:
            # Cleanup temp file
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _flatten_java_directory(self, java_home: Path):
        """Flatten extracted Java directory (remove versioned subfolder)."""
        # After extraction, there's usually a folder like 'jdk-17.0.8+7-jre'
        # We want the contents directly in java_home
        items = list(java_home.iterdir())
        if len(items) == 1 and items[0].is_dir():
            inner = items[0]
            # Move contents up
            for item in inner.iterdir():
                target = java_home / item.name
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))
            # Remove empty inner directory
            inner.rmdir()

    def ensure_java(self, required_version: int, progress_callback=None) -> JavaInstallation:
        """
        Ensure Java is available: check local, check system, download if needed.
        Returns JavaInstallation object.
        """
        # 1. Check local runtime
        local = self.check_java_installed(required_version)
        if local.is_valid:
            return local
        
        # 2. Check system Java
        system = self.find_system_java(required_version)
        if system and system.is_valid:
            return system
        
        # 3. Download
        if progress_callback:
            progress_callback(0, 1)  # Starting download
        
        success = self.download_java(required_version, progress_callback)
        
        # 4. Verify
        final = self.check_java_installed(required_version)
        if not final.is_valid:
            final.error = f"Download/verification failed: {final.error}"
        return final

    def get_java_version_output(self, java_path: Path) -> str:
        """Get full java -version output for display."""
        try:
            result = subprocess.run(
                [str(java_path), "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stderr.strip() + "\n" + result.stdout.strip()
        except Exception:
            return "Unknown"