import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from core.manifest import Manifest, ManifestFile


@dataclass
class FileStatus:
    file: ManifestFile
    status: str  # "missing", "ok", "corrupted", "size_mismatch"
    local_path: Path

    @property
    def needs_download(self) -> bool:
        return self.status in ("missing", "corrupted", "size_mismatch")


class FileChecker:
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def compute_sha1(self, file_path: Path) -> str:
        sha1 = hashlib.sha1()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha1.update(chunk)
        return sha1.hexdigest()

    def check_file(self, manifest_file: ManifestFile) -> FileStatus:
        local_path = self.base_path / manifest_file.path

        if not local_path.exists():
            return FileStatus(
                file=manifest_file,
                status="missing",
                local_path=local_path
            )

        # Check size first (fast)
        try:
            actual_size = local_path.stat().st_size
            if actual_size != manifest_file.size:
                return FileStatus(
                    file=manifest_file,
                    status="size_mismatch",
                    local_path=local_path
                )
        except OSError:
            return FileStatus(
                file=manifest_file,
                status="corrupted",
                local_path=local_path
            )

        # Check SHA-1
        try:
            actual_sha1 = self.compute_sha1(local_path)
            if actual_sha1.lower() != manifest_file.sha1.lower():
                return FileStatus(
                    file=manifest_file,
                    status="corrupted",
                    local_path=local_path
                )
        except Exception:
            return FileStatus(
                file=manifest_file,
                status="corrupted",
                local_path=local_path
            )

        return FileStatus(
            file=manifest_file,
            status="ok",
            local_path=local_path
        )

    def check_all(self, manifest: Manifest) -> list[FileStatus]:
        results = []
        for manifest_file in manifest.files:
            results.append(self.check_file(manifest_file))
        return results

    def get_files_to_download(self, manifest: Manifest) -> list[ManifestFile]:
        statuses = self.check_all(manifest)
        return [s.file for s in statuses if s.needs_download]

    def get_summary(self, manifest: Manifest) -> dict:
        statuses = self.check_all(manifest)
        total = len(statuses)
        ok = sum(1 for s in statuses if s.status == "ok")
        missing = sum(1 for s in statuses if s.status == "missing")
        corrupted = sum(1 for s in statuses if s.status == "corrupted")
        size_mismatch = sum(1 for s in statuses if s.status == "size_mismatch")
        to_download = missing + corrupted + size_mismatch
        total_size = sum(f.size for f in manifest.files)
        download_size = sum(f.size for f in manifest.files
                            for s in statuses if s.file.path == f.path and s.needs_download)

        return {
            "total_files": total,
            "ok": ok,
            "missing": missing,
            "corrupted": corrupted,
            "size_mismatch": size_mismatch,
            "to_download": to_download,
            "total_size_bytes": total_size,
            "download_size_bytes": download_size
        }