"""
Official Minecraft: Java Edition release versions.

Fetches the version manifest published by Mojang and exposes the release-only
versions (snapshots are filtered out). Also provides the Minecraft -> Java
version mapping needed to pick a runtime.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
import minecraft_launcher_lib.utils as mcl_utils

from core.manifest import Manifest, ManifestLoader


VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_USER_AGENT = "minecraft-launcher-lib/melon-launcher"


@dataclass(frozen=True)
class OfficialVersion:
    """A single release version of Minecraft: Java Edition."""

    id: str
    release_time: str

    @property
    def display_name(self) -> str:
        return self.id


_versions_cache: Optional[List[OfficialVersion]] = None


def get_official_releases(force_refresh: bool = False) -> List[OfficialVersion]:
    """
    Return all official release versions, newest first.

    Snapshots, alpha and beta versions are filtered out.
    Results are cached in-process because the manifest changes rarely.
    """
    global _versions_cache

    if _versions_cache is not None and not force_refresh:
        return _versions_cache

    versions: List[OfficialVersion] = []
    for entry in mcl_utils.get_version_list():
        if entry.get("type") != "release":
            continue
        versions.append(
            OfficialVersion(
                id=str(entry["id"]),
                release_time=str(entry.get("releaseTime") or ""),
            )
        )

    _versions_cache = versions
    return versions


def get_required_java_version(minecraft_version: str) -> int:
    """
    Return the Java major version required by a Minecraft version.

    * 1.17 - 1.20.4  -> Java 17
    * 1.20.5+         -> Java 21
    * 1.21+           -> Java 21
    * anything older  -> Java 8
    * new major scheme (e.g. 26.1) -> Java 21
    """
    parts = str(minecraft_version).split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return 17

    # New versioning scheme (26.x and above)
    if major > 1:
        return 21

    if minor >= 21:
        return 21
    if minor == 20:
        return 21 if patch >= 5 else 17
    if 17 <= minor <= 19:
        return 17
    return 8


def _default_ram_for(java_version: int) -> tuple[int, int]:
    """Sensible min/recommended RAM per Java generation."""
    if java_version >= 21:
        return 2048, 4096
    if java_version >= 17:
        return 2048, 4096
    return 1024, 2048


def build_vanilla_manifest(minecraft_version: str) -> Manifest:
    """
    Build a Manifest describing an official, unmodified Minecraft version.
    """
    java_version = get_required_java_version(minecraft_version)
    min_ram, rec_ram = _default_ram_for(java_version)

    return Manifest(
        id=f"vanilla-{minecraft_version}",
        name=f"Minecraft {minecraft_version}",
        version=minecraft_version,
        minecraft_version=minecraft_version,
        loader=ManifestLoader("vanilla", ""),
        java_version=java_version,
        icon_url="",
        description=(
            f"Официальная версия Minecraft {minecraft_version} "
            f"без модификаций. Требуется Java {java_version}."
        ),
        min_ram_mb=min_ram,
        recommended_ram_mb=rec_ram,
        files=[],
    )


def is_official_version(version_id: str) -> bool:
    """Check if the given id is a known official release version."""
    return any(v.id == version_id for v in get_official_releases())


# ==================== INSTALL SIZE / FILE COUNT ====================

_stats_cache: Dict[str, Dict[str, int]] = {}
_version_urls: Optional[Dict[str, str]] = None


def _get_version_urls() -> Dict[str, str]:
    """Map of version id -> version json url (cached)."""
    global _version_urls
    if _version_urls is not None:
        return _version_urls

    response = requests.get(
        VERSION_MANIFEST_URL,
        timeout=30,
        headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    _version_urls = {
        entry["id"]: entry["url"]
        for entry in response.json().get("versions", [])
    }
    return _version_urls


def get_install_stats(version_id: str) -> Dict[str, int]:
    """
    Return {'files': int, 'size': int} for an official Minecraft version.

    Counts the client jar, all libraries and all assets, and sums their
    download sizes as reported by Mojang. Results are cached per version.
    """
    if version_id in _stats_cache:
        return _stats_cache[version_id]

    empty = {"files": 0, "size": 0}

    try:
        url = _get_version_urls().get(version_id)
        if not url:
            return empty

        response = requests.get(
            url, timeout=30, headers={"User-Agent": _USER_AGENT}
        )
        response.raise_for_status()
        data = response.json()

        file_count = 0
        total_size = 0

        # Client jar
        client = (data.get("downloads") or {}).get("client")
        if client:
            file_count += 1
            total_size += int(client.get("size", 0))

        # Libraries (artifact + native classifiers)
        for library in data.get("libraries", []):
            downloads = library.get("downloads") or {}
            if downloads.get("artifact"):
                file_count += 1
                total_size += int(downloads["artifact"].get("size", 0))
            for classifier in (downloads.get("classifiers") or {}).values():
                if isinstance(classifier, dict):
                    file_count += 1
                    total_size += int(classifier.get("size", 0))

        # Assets
        asset_index = data.get("assetIndex") or {}
        asset_url = asset_index.get("url")
        if asset_url:
            assets_response = requests.get(
                asset_url, timeout=30, headers={"User-Agent": _USER_AGENT}
            )
            assets_response.raise_for_status()
            objects = assets_response.json().get("objects", {})
            file_count += len(objects)
            total_size += sum(int(obj.get("size", 0)) for obj in objects.values())

        stats = {"files": file_count, "size": total_size}
        _stats_cache[version_id] = stats
        return stats

    except Exception:
        return empty


# ==================== INSTALLED VERSIONS ====================


def _version_dir(minecraft_directory: Path, version_id: str) -> Path:
    """Resolve and validate the install folder of a version."""
    if not version_id or version_id in (".", ".."):
        raise ValueError(f"Недопустимый идентификатор версии: {version_id!r}")

    # Guard against path traversal ("..\\..", "1.21.1/../../etc", ...).
    if any(sep in version_id for sep in ("/", "\\")) or Path(version_id).name != version_id:
        raise ValueError(f"Недопустимый идентификатор версии: {version_id!r}")

    return Path(minecraft_directory) / "versions" / version_id


def is_version_installed(minecraft_directory: Path, version_id: str) -> bool:
    """True when the version jar is present on disk."""
    try:
        return (_version_dir(minecraft_directory, version_id) / f"{version_id}.jar").exists()
    except ValueError:
        return False


def get_installed_stats(minecraft_directory: Path, version_id: str) -> Dict[str, int]:
    """
    Return {'files': int, 'size': int} measured on disk for an installed version.

    Only the version folder itself is measured: libraries and assets are shared
    between versions, so counting them here would be misleading.
    """
    empty = {"files": 0, "size": 0}

    try:
        directory = _version_dir(minecraft_directory, version_id)
    except ValueError:
        return empty

    if not directory.is_dir():
        return empty

    files = 0
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            files += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass

    return {"files": files, "size": total}


def get_installed_size(minecraft_directory: Path, version_id: str) -> int:
    """Disk size in bytes occupied by an installed version."""
    return get_installed_stats(minecraft_directory, version_id)["size"]


def delete_installed_version(minecraft_directory: Path, version_id: str) -> int:
    """
    Remove an installed version from disk and return the freed size in bytes.

    Only ``versions/<id>`` is removed - the shared ``libraries`` and ``assets``
    folders are kept because other installed versions still depend on them.
    """
    import shutil

    directory = _version_dir(minecraft_directory, version_id)
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Версия {version_id} не установлена"
        )

    freed = get_installed_size(minecraft_directory, version_id)
    shutil.rmtree(directory)
    return freed