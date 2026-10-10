"""
Built-in manifests for Vanilla, Fabric, and Forge profiles.
These provide real manifest data for the built-in profiles so they work like custom builds.
"""

from core.manifest import Manifest, ManifestFile, ManifestLoader
from typing import Dict, List


# Vanilla 1.20.4 manifest (no mods, just base game)
VANILLA_1_20_4_MANIFEST = Manifest(
    id="vanilla-1.20.4",
    name="Vanilla 1.20.4",
    version="1.20.4",
    minecraft_version="1.20.4",
    loader=ManifestLoader("vanilla", ""),
    java_version=17,
    icon_url="",
    description="Официальная версия Minecraft 1.20.4 без модификаций. Чистый ванильный опыт с последними обновлениями.",
    min_ram_mb=2048,
    recommended_ram_mb=4096,
    files=[]
)

# Fabric 1.20.4 manifest (with Fabric loader)
FABRIC_1_20_4_MANIFEST = Manifest(
    id="fabric-1.20.4",
    name="Fabric 1.20.4",
    version="1.20.4-fabric-0.15.11",
    minecraft_version="1.20.4",
    loader=ManifestLoader("fabric", "0.15.11"),
    java_version=17,
    icon_url="",
    description="Лёгкий и быстрый модлоадер Fabric 0.15.11 для Minecraft 1.20.4 с базовыми оптимизациями и API для модов.",
    min_ram_mb=3072,
    recommended_ram_mb=5120,
    files=[]
)

# Forge 1.20.4 manifest (with Forge loader)
FORGE_1_20_4_MANIFEST = Manifest(
    id="forge-1.20.4",
    name="Forge 1.20.4",
    version="1.20.4-forge-49.0.0",
    minecraft_version="1.20.4",
    loader=ManifestLoader("forge", "49.0.0"),
    java_version=17,
    icon_url="",
    description="Популярный модлоадер Forge 49.0.0 для Minecraft 1.20.4 с поддержкой огромного количества модов и аддонов.",
    min_ram_mb=4096,
    recommended_ram_mb=6144,
    files=[]
)

# Additional versions
VANILLA_1_21_MANIFEST = Manifest(
    id="vanilla-1.21",
    name="Vanilla 1.21",
    version="1.21",
    minecraft_version="1.21",
    loader=ManifestLoader("vanilla", ""),
    java_version=21,
    icon_url="",
    description="Официальная версия Minecraft 1.21 (Tricky Trials) без модификаций.",
    min_ram_mb=2048,
    recommended_ram_mb=4096,
    files=[]
)

FABRIC_1_21_MANIFEST = Manifest(
    id="fabric-1.21",
    name="Fabric 1.21",
    version="1.21-fabric-0.16.0",
    minecraft_version="1.21",
    loader=ManifestLoader("fabric", "0.16.0"),
    java_version=21,
    icon_url="",
    description="Fabric 0.16.0 для Minecraft 1.21.",
    min_ram_mb=3072,
    recommended_ram_mb=5120,
    files=[]
)

FORGE_1_21_MANIFEST = Manifest(
    id="forge-1.21",
    name="Forge 1.21",
    version="1.21-forge-50.0.0",
    minecraft_version="1.21",
    loader=ManifestLoader("forge", "50.0.0"),
    java_version=21,
    icon_url="",
    description="Forge 50.0.0 для Minecraft 1.21.",
    min_ram_mb=4096,
    recommended_ram_mb=6144,
    files=[]
)

# Registry of all built-in manifests
BUILTIN_MANIFESTS: Dict[str, Manifest] = {
    "Vanilla 1.20.4": VANILLA_1_20_4_MANIFEST,
    "Fabric 1.20.4": FABRIC_1_20_4_MANIFEST,
    "Forge 1.20.4": FORGE_1_20_4_MANIFEST,
    "Vanilla 1.21": VANILLA_1_21_MANIFEST,
    "Fabric 1.21": FABRIC_1_21_MANIFEST,
    "Forge 1.21": FORGE_1_21_MANIFEST,
}

BUILTIN_PROFILES: List[str] = list(BUILTIN_MANIFESTS.keys())


def get_builtin_manifest(profile_name: str) -> Manifest | None:
    """Get built-in manifest by profile name."""
    return BUILTIN_MANIFESTS.get(profile_name)


def get_builtin_profiles() -> List[str]:
    """Get list of all built-in profile names."""
    return BUILTIN_PROFILES.copy()


def is_builtin_profile(profile_name: str) -> bool:
    """Check if profile is a built-in profile."""
    return profile_name in BUILTIN_MANIFESTS