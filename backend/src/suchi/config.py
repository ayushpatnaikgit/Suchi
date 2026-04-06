"""Configuration management for Suchi."""

from pathlib import Path
from dataclasses import dataclass, field
import yaml


DEFAULT_LIBRARY_DIR = Path.home() / "Documents" / "Suchi Library"
CONFIG_DIR = Path.home() / ".config" / "suchi"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass
class SyncConfig:
    backend: str = "none"  # "none", "gdrive"
    auto_sync: bool = False
    sync_interval_minutes: int = 15
    gdrive_folder_id: str | None = None


@dataclass
class AIConfig:
    gemini_api_key: str = ""
    model: str = "gemini-2.5-flash"


@dataclass
class Config:
    library_dir: Path = field(default_factory=lambda: DEFAULT_LIBRARY_DIR)
    sync: SyncConfig = field(default_factory=SyncConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    default_export_format: str = "bibtex"
    editor: str = ""  # Falls back to $EDITOR

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = yaml.safe_load(f) or {}
            sync_data = data.pop("sync", {})
            ai_data = data.pop("ai", {})
            return cls(
                library_dir=Path(data.get("library_dir", DEFAULT_LIBRARY_DIR)),
                sync=SyncConfig(**sync_data),
                ai=AIConfig(**ai_data),
                default_export_format=data.get("default_export_format", "bibtex"),
                editor=data.get("editor", ""),
            )
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "library_dir": str(self.library_dir),
            "sync": {
                "backend": self.sync.backend,
                "auto_sync": self.sync.auto_sync,
                "sync_interval_minutes": self.sync.sync_interval_minutes,
                "gdrive_folder_id": self.sync.gdrive_folder_id,
            },
            "ai": {
                "gemini_api_key": self.ai.gemini_api_key,
                "model": self.ai.model,
            },
            "default_export_format": self.default_export_format,
            "editor": self.editor,
        }
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False)


def get_config() -> Config:
    return Config.load()
