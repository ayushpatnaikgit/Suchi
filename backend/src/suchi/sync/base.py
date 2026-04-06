"""Storage backend protocol for cloud sync."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Change:
    path: str          # Relative path within the library
    action: str        # "added", "modified", "deleted"
    checksum: str | None = None


class StorageBackend(Protocol):
    """Protocol that all storage backends must implement."""

    def authenticate(self) -> None:
        """Run OAuth or other auth flow."""
        ...

    def upload(self, local_path: Path, remote_path: str) -> None:
        """Upload a local file to the remote storage."""
        ...

    def download(self, remote_path: str, local_path: Path) -> None:
        """Download a remote file to a local path."""
        ...

    def delete(self, remote_path: str) -> None:
        """Delete a file from remote storage."""
        ...

    def list_remote_changes(self, since_token: str | None) -> tuple[list[Change], str]:
        """List changes since the given token. Returns (changes, new_token)."""
        ...
