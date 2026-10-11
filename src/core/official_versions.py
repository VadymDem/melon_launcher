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
    """A single version of Minecraft: Java Edition."""

    id: str
    release_time: str
    # "release", "snapshot", "old_beta" or "old_alpha" as Mojang reports it.
    type: str = "release"

    @property
    def display_name(self) -> str:
        return self.id

    @property
    def is_release(self) -> bool:
        return self.type == "release"

    @property
    def is_snapshot(self) -> bool:
        return self.type == "snapshot"

    @property
    def is_beta(self) -> bool:
        return self.type == "old_beta"

    @property
    def is_alpha(self) -> bool:
        return self.type == "old_alpha"

    @property
    def category(self) -> str:
        """Filter category used by the toolbar chips."""
        return {
            "release": "Release",
            "snapshot": "Snapshot",
            "old_beta": "Beta",
            "old_alpha": "Alpha",
        }.get(self.type, "Release")

    @property
    def category_key(self) -> str:
        """Lowercase key used by the filter comparisons."""
        return self.category.lower()


_versions_cache: Optional[List[OfficialVersion]] = None


def get_all_versions(force_refresh: bool = False) -> List[OfficialVersion]:
    """
    Return every official version Mojang publishes, newest first.

    Includes releases as well as snapshots, beta and alpha builds. Results are
    cached in-process because the manifest changes rarely.
    """
    global _versions_cache

    if _versions_cache is not None and not force_refresh:
        return _versions_cache

    versions: List[OfficialVersion] = []
    for entry in mcl_utils.get_version_list():
        entry_type = str(entry.get("type") or "release")
        if entry_type not in ("release", "snapshot", "old_beta", "old_alpha"):
            continue
        versions.append(
            OfficialVersion(
                id=str(entry["id"]),
                release_time=str(entry.get("releaseTime") or ""),
                type=entry_type,
            )
        )

    _versions_cache = versions
    return versions


def get_official_releases(force_refresh: bool = False) -> List[OfficialVersion]:
    """
    Return official release versions only, newest first.

    Snapshots, beta and alpha builds are filtered out. Results are cached
    in-process because the manifest changes rarely.
    """
    return [v for v in get_all_versions(force_refresh) if v.is_release]


def _parse_version_numbers(minecraft_version: str) -> tuple[int, int, int]:
    """
    Extract the leading numeric triple from a Minecraft version id.

    Handles ids that carry a non-numeric part: snapshots
    (``26.4-snapshot-3``), betas (``b1.8.1``) and alphas (``a1.2.6``). The
    leading letters of beta/alpha ids are dropped so their numbers are read
    like a classic ``1.8.1`` version.
    """
    text = str(minecraft_version).strip().lower()

    # Strip the leading letters used by beta/alpha builds (b1.8.1, a1.2.6).
    while text and not text[0].isdigit():
        text = text[1:]

    # Keep only the numeric segments of the first components; suffixes such as
    # "-snapshot-3", "-rc-1" or "_04" are not version numbers.
    segments = []
    for chunk in text.replace("_", ".").split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            break
        segments.append(int(digits))

    major = segments[0] if len(segments) > 0 else 0
    minor = segments[1] if len(segments) > 1 else 0
    patch = segments[2] if len(segments) > 2 else 0
    return major, minor, patch


def get_required_java_version(minecraft_version: str) -> int:
    """
    Return the Java major version required by a Minecraft version.

    * 1.17 - 1.20.4  -> Java 17
    * 1.20.5+         -> Java 21
    * 1.21+           -> Java 21
    * anything older  -> Java 8
    * new major scheme (e.g. 26.1) -> Java 21
    """
    major, minor, patch = _parse_version_numbers(minecraft_version)

    # New versioning scheme (26.x and above). Includes snapshots of it.
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


# ==================== ON-DISK VERSION CACHE ====================
# The manifest holds ~900 entries; fetching and parsing it on every start is
# slow, and it changes rarely. The list is therefore stored next to the other
# launcher data and only refetched when the user asks for it.

_VERSION_CACHE_FILE = "versions_cache.json"


def _cache_path(install_path) -> Path:
    return Path(install_path) / _VERSION_CACHE_FILE


def load_cached_versions(install_path) -> List[OfficialVersion]:
    """Read the version list from disk. Returns an empty list when absent."""
    import json

    path = _cache_path(install_path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    versions = []
    for entry in data:
        try:
            versions.append(
                OfficialVersion(
                    id=str(entry["id"]),
                    release_time=str(entry.get("release_time") or ""),
                    type=str(entry.get("type") or "release"),
                )
            )
        except (KeyError, TypeError):
            continue
    return versions


def save_cached_versions(install_path, versions: List[OfficialVersion]) -> bool:
    """Write the version list to disk. Returns True on success."""
    import json

    path = _cache_path(install_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"id": v.id, "release_time": v.release_time, "type": v.type}
            for v in versions
        ]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        return True
    except OSError:
        return False


def get_versions_cached(install_path, force_refresh: bool = False) -> List[OfficialVersion]:
    """
    Version list for the UI: cache first, network only when asked.

    On a normal start the list comes straight from disk, so the "Версии" page
    opens instantly. ``force_refresh`` goes back to Mojang and rewrites the
    cache.
    """
    global _versions_cache

    if not force_refresh:
        cached = load_cached_versions(install_path)
        if cached:
            _versions_cache = cached
            return cached

    versions = get_all_versions(force_refresh=True)
    if versions:
        save_cached_versions(install_path, versions)
    return versions