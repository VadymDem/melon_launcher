"""
Per-instance folders.

Every pack gets its own game directory (``<install_path>/instances/<pack_id>``)
so worlds, mods, resource packs and options never leak between versions.

The launcher's own data - ``versions``, ``libraries``, ``assets``, ``auth.json``
- stays in the shared install root; only what Minecraft itself writes at runtime
is moved into the instance folder.
"""

from pathlib import Path
from typing import List


# Folders Minecraft expects to be able to write into at runtime.
INSTANCE_SUBDIRS = [
    "saves",
    "config",
    "mods",
    "resourcepacks",
    "shaderpacks",
    "screenshots",
    "logs",
]

# Files that belong to a single instance rather than to the launcher.
INSTANCE_FILES = ["options.txt", "servers.dat", "usercache.json", "banned-players.json"]

# Folders the game fills on its own - their presence says nothing about usage.
IGNORED_SUBDIRS = ["logs", "screenshots", "shaderpacks"]


def safe_folder_name(pack_id: str) -> str:
    """
    Turn a pack id into a single safe folder name.

    Guards against path traversal and characters Windows does not accept, so an
    id can never point the instance folder outside of ``instances``.
    """
    name = str(pack_id).strip()

    if not name or name in (".", ".."):
        raise ValueError(f"Недопустимый идентификатор инстанса: {pack_id!r}")

    # Anything that looks like a path is rejected outright rather than cleaned.
    if any(sep in name for sep in ("/", "\\", ":")) or Path(name).name != name:
        raise ValueError(f"Недопустимый идентификатор инстанса: {pack_id!r}")

    for bad in '<>:"|?*':
        name = name.replace(bad, "_")

    return name.strip(". ") or "instance"


def instances_root(install_path: Path) -> Path:
    """Folder that holds one subfolder per instance."""
    return Path(install_path) / "instances"


def get_instance_dir(install_path: Path, pack_id: str) -> Path:
    """Path of the instance folder for a pack (may not exist yet)."""
    return instances_root(install_path) / safe_folder_name(pack_id)


def ensure_instance_dir(install_path: Path, pack_id: str) -> Path:
    """
    Create the instance folder and its standard subfolders if needed.

    Returns the instance folder path.
    """
    instance = get_instance_dir(install_path, pack_id)
    instance.mkdir(parents=True, exist_ok=True)

    for name in INSTANCE_SUBDIRS:
        (instance / name).mkdir(parents=True, exist_ok=True)

    return instance


def instance_exists(install_path: Path, pack_id: str) -> bool:
    """True when the instance folder has already been created."""
    try:
        return get_instance_dir(install_path, pack_id).is_dir()
    except ValueError:
        return False


def is_instance_empty(install_path: Path, pack_id: str) -> bool:
    """
    True when the instance folder holds no worlds, mods or user settings.

    Folders the game fills on its own (logs, screenshots, shaderpacks) and the
    default files it writes do not count as user content, so this answers "did
    the player actually put anything in here".
    """
    try:
        instance = get_instance_dir(install_path, pack_id)
    except ValueError:
        return True

    if not instance.is_dir():
        return True

    for entry in instance.iterdir():
        if entry.is_dir():
            if entry.name in IGNORED_SUBDIRS:
                continue
            if entry.name in INSTANCE_SUBDIRS:
                if any(entry.iterdir()):
                    return False
                continue
            # Unknown folder - treat it as user content.
            return False

        if entry.name in INSTANCE_FILES:
            continue

        return False

    return True


def remove_empty_instance(install_path: Path, pack_id: str) -> bool:
    """
    Delete the instance folder when the user never used it.

    Returns True when a folder was actually removed. Instances that contain
    worlds or mods are kept so player data is never lost silently.
    """
    import shutil

    try:
        instance = get_instance_dir(install_path, pack_id)
    except ValueError:
        return False

    if not instance.is_dir():
        return False

    if not is_instance_empty(install_path, pack_id):
        return False

    shutil.rmtree(instance, ignore_errors=True)
    return True


def list_instances(install_path: Path) -> List[str]:
    """Ids of every instance folder that exists on disk."""
    root = instances_root(install_path)
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())