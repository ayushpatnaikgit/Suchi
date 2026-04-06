"""Settings API routes."""

from pydantic import BaseModel
from fastapi import APIRouter

from ..config import get_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    library_dir: str
    sync_backend: str
    auto_sync: bool
    sync_interval_minutes: int
    gdrive_folder_id: str | None
    default_export_format: str
    editor: str
    gemini_api_key: str
    gemini_model: str


class SettingsUpdate(BaseModel):
    library_dir: str | None = None
    sync_backend: str | None = None
    auto_sync: bool | None = None
    sync_interval_minutes: int | None = None
    gdrive_folder_id: str | None = None
    default_export_format: str | None = None
    editor: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None


def _config_to_response() -> SettingsResponse:
    config = get_config()
    return SettingsResponse(
        library_dir=str(config.library_dir),
        sync_backend=config.sync.backend,
        auto_sync=config.sync.auto_sync,
        sync_interval_minutes=config.sync.sync_interval_minutes,
        gdrive_folder_id=config.sync.gdrive_folder_id,
        default_export_format=config.default_export_format,
        editor=config.editor,
        gemini_api_key=config.ai.gemini_api_key,
        gemini_model=config.ai.model,
    )


@router.get("", response_model=SettingsResponse)
def get_settings():
    return _config_to_response()


@router.put("", response_model=SettingsResponse)
def update_settings(data: SettingsUpdate):
    config = get_config()

    if data.library_dir is not None:
        from pathlib import Path
        config.library_dir = Path(data.library_dir)
    if data.sync_backend is not None:
        config.sync.backend = data.sync_backend
    if data.auto_sync is not None:
        config.sync.auto_sync = data.auto_sync
    if data.sync_interval_minutes is not None:
        config.sync.sync_interval_minutes = data.sync_interval_minutes
    if data.gdrive_folder_id is not None:
        config.sync.gdrive_folder_id = data.gdrive_folder_id
    if data.default_export_format is not None:
        config.default_export_format = data.default_export_format
    if data.editor is not None:
        config.editor = data.editor
    if data.gemini_api_key is not None:
        config.ai.gemini_api_key = data.gemini_api_key
    if data.gemini_model is not None:
        config.ai.model = data.gemini_model

    config.save()
    return _config_to_response()
