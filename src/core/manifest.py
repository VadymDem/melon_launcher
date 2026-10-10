import json
import hashlib
import requests
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin


@dataclass
class ManifestFile:
    path: str
    url: str
    sha1: str
    size: int

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "url": self.url,
            "sha1": self.sha1,
            "size": self.size
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestFile":
        return cls(
            path=data["path"],
            url=data["url"],
            sha1=data["sha1"],
            size=data["size"]
        )


@dataclass
class ManifestLoader:
    type: str
    version: str

    def to_dict(self) -> dict:
        return {"type": self.type, "version": self.version}

    @classmethod
    def from_dict(cls, data: dict) -> "ManifestLoader":
        return cls(type=data["type"], version=data["version"])


@dataclass
class Manifest:
    id: str
    name: str
    version: str
    minecraft_version: str
    loader: ManifestLoader
    java_version: int
    icon_url: str = ""
    description: str = ""
    min_ram_mb: int = 2048
    recommended_ram_mb: int = 4096
    files: list[ManifestFile] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "minecraftVersion": self.minecraft_version,
            "loader": self.loader.to_dict(),
            "javaVersion": self.java_version,
            "iconUrl": self.icon_url,
            "description": self.description,
            "minRamMb": self.min_ram_mb,
            "recommendedRamMb": self.recommended_ram_mb,
            "files": [f.to_dict() for f in self.files]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            minecraft_version=data["minecraftVersion"],
            loader=ManifestLoader.from_dict(data["loader"]),
            java_version=data["javaVersion"],
            icon_url=data.get("iconUrl", ""),
            description=data.get("description", ""),
            min_ram_mb=data.get("minRamMb", 2048),
            recommended_ram_mb=data.get("recommendedRamMb", 4096),
            files=[ManifestFile.from_dict(f) for f in data.get("files", [])]
        )

    def get_total_size(self) -> int:
        return sum(f.size for f in self.files)


REQUIRED_FIELDS = [
    "id", "name", "version", "minecraftVersion",
    "loader", "javaVersion"
]

REQUIRED_LOADER_FIELDS = ["type", "version"]

REQUIRED_FILE_FIELDS = ["path", "url", "sha1", "size"]


def validate_manifest(data: dict) -> tuple[bool, list[str]]:
    errors = []

    for field_name in REQUIRED_FIELDS:
        if field_name not in data:
            errors.append(f"Missing required field: {field_name}")

    if "loader" in data:
        loader = data["loader"]
        if not isinstance(loader, dict):
            errors.append("loader must be an object")
        else:
            for field_name in REQUIRED_LOADER_FIELDS:
                if field_name not in loader:
                    errors.append(f"Missing required loader field: {field_name}")

    if "files" in data:
        files = data["files"]
        if not isinstance(files, list):
            errors.append("files must be an array")
        else:
            for i, file_data in enumerate(files):
                if not isinstance(file_data, dict):
                    errors.append(f"File {i}: must be an object")
                    continue
                for field_name in REQUIRED_FILE_FIELDS:
                    if field_name not in file_data:
                        errors.append(f"File {i}: missing required field {field_name}")

    return len(errors) == 0, errors