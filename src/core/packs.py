"""
Installed packs ("паки") - the game instances the user can launch.

Only instances that are actually present on disk are listed here. Official
Minecraft versions are installed from the "Версии" page and then show up here
as ready-to-play packs; installing is never triggered from the home page.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.official_versions import (
    get_installed_stats,
    get_required_java_version,
    is_version_installed,
)


@dataclass(frozen=True)
class InstalledPack:
    """A launchable pack installed in ``<install_path>/versions/<id>``."""

    id: str
    minecraft_version: str
    loader: str
    java_version: int
    size_bytes: int
    file_count: int
    last_played: Optional[datetime] = None

    @property
    def display_name(self) -> str:
        return f"Minecraft {self.id}"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def version_sort_key(version_id: str) -> tuple:
    """
    Sort key that puts the newest release first.

    Handles both numbering schemes: the new major scheme (``26.3``) and the
    classic one (``1.21.1``). A plain string sort would put "26.3" before
    "1.21.1" for the wrong reason, so the parts are compared numerically.
    """
    parts = []
    for chunk in str(version_id).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)

    return (parts[0], parts[1], parts[2])


def _read_last_played(minecraft_directory: Path, version_id: str) -> Optional[datetime]:
    """Best-effort last launch time taken from the install folder mtime."""
    folder = Path(minecraft_directory) / "versions" / version_id
    try:
        return datetime.fromtimestamp(folder.stat().st_mtime, tz=timezone.utc)
    except (OSError, ValueError):
        return None


def get_installed_packs(minecraft_directory: Path) -> List[InstalledPack]:
    """
    Return every installed pack, newest version first.

    A directory only counts as a pack when its jar is actually present, so
    half-finished downloads never show up in the list.
    """
    root = Path(minecraft_directory) / "versions"
    if not root.is_dir():
        return []

    packs = []
    for folder in root.iterdir():
        if not folder.is_dir() or not is_version_installed(minecraft_directory, folder.name):
            continue

        stats = get_installed_stats(minecraft_directory, folder.name)
        packs.append(
            InstalledPack(
                id=folder.name,
                minecraft_version=folder.name,
                loader="Vanilla",
                java_version=get_required_java_version(folder.name),
                size_bytes=stats["size"],
                file_count=stats["files"],
                last_played=_read_last_played(minecraft_directory, folder.name),
            )
        )

    packs.sort(key=lambda pack: version_sort_key(pack.id), reverse=True)
    return packs


def get_pack(minecraft_directory: Path, pack_id: str) -> Optional[InstalledPack]:
    """Return a single installed pack, or None when it is not installed."""
    if not pack_id or not is_version_installed(minecraft_directory, pack_id):
        return None

    stats = get_installed_stats(minecraft_directory, pack_id)
    return InstalledPack(
        id=pack_id,
        minecraft_version=pack_id,
        loader="Vanilla",
        java_version=get_required_java_version(pack_id),
        size_bytes=stats["size"],
        file_count=stats["files"],
        last_played=_read_last_played(minecraft_directory, pack_id),
    )


def sort_packs(packs: List[InstalledPack]) -> List[InstalledPack]:
    """Newest version first, most recently played first as a tiebreaker."""
    return sorted(
        packs,
        key=lambda pack: (
            version_sort_key(pack.id),
            pack.last_played.timestamp() if pack.last_played else 0,
        ),
        reverse=True,
    )