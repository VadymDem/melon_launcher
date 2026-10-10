import json
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class Config:
    manifest_url: str = ""
    ram_mb: int = 2048
    auth_type: str = "offline"  # "microsoft" or "offline"
    install_path: str = ""
    username: str = "Player"
    last_profile: str = ""
    java_version: int = 17
    custom_jvm_args: str = ""
    # Azure app (client) id used for the Microsoft/Minecraft login.
    # Minecraft Services only accepts allowlisted client ids - see
    # https://aka.ms/mce-reviewappid for registering your own app.
    microsoft_client_id: str = "3b42bcd5-9b4e-4f8b-85e8-5f3a749d0267"

    def __post_init__(self):
        if not self.install_path:
            self.install_path = str(Path.home() / ".melon_launcher")

    def load(self):
        config_path = Path(self.install_path) / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(self, key):
                            setattr(self, key, value)
            except Exception:
                pass

    def save(self):
        config_path = Path(self.install_path) / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception:
            pass