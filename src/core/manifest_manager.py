import json
import requests
from pathlib import Path
from typing import Optional

from core.manifest import Manifest, validate_manifest, ManifestFile


class ManifestManager:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MelonLauncher/1.0"
        })

    def fetch_manifest(self, url: str) -> Optional[Manifest]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            valid, errors = validate_manifest(data)
            if not valid:
                raise ValueError(f"Manifest validation failed: {', '.join(errors)}")

            return Manifest.from_dict(data)

        except requests.RequestException as e:
            raise ConnectionError(f"Failed to fetch manifest: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in manifest: {e}")
        except Exception as e:
            raise ValueError(f"Manifest processing error: {e}")

    def fetch_manifest_with_base(self, base_url: str, manifest_name: str = "modpack.json") -> Optional[Manifest]:
        if base_url.endswith("/"):
            url = base_url + manifest_name
        else:
            url = base_url + "/" + manifest_name
        return self.fetch_manifest(url)

    def load_local_manifest(self, path: Path) -> Optional[Manifest]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            valid, errors = validate_manifest(data)
            if not valid:
                raise ValueError(f"Manifest validation failed: {', '.join(errors)}")

            return Manifest.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in local manifest: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load local manifest: {e}")

    def save_manifest(self, manifest: Manifest, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)

    def resolve_file_url(self, base_url: str, file_url: str) -> str:
        if file_url.startswith(("http://", "https://")):
            return file_url
        if base_url.endswith("/"):
            return base_url + file_url
        return base_url + "/" + file_url