"""Entry point for the bundled Suchi backend server (PyInstaller)."""

import logging
import os
import sys
from pathlib import Path


def _setup_logging() -> Path:
    """Write all backend logs to ~/.config/suchi/logs/suchi-server.log.

    Both the file and stdout are written to, so users can either tail the
    file via `suchi logs` or see live output by running the .app from terminal.
    """
    log_dir = Path.home() / ".config" / "suchi" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "suchi-server.log"

    # Rotate if larger than 10 MB — keep one previous log
    try:
        if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:
            prev = log_dir / "suchi-server.log.1"
            if prev.exists():
                prev.unlink()
            log_file.rename(prev)
    except OSError:
        pass

    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("suchi-server").info("Starting suchi-server (pid=%d)", os.getpid())
    return log_file


if __name__ == "__main__":
    log_file = _setup_logging()
    try:
        import uvicorn
        uvicorn.run(
            "suchi.api:app",
            host="127.0.0.1",
            port=9876,
            log_level="info",
            log_config=None,  # Use our root logger config
        )
    except Exception as e:
        logging.getLogger("suchi-server").exception("suchi-server crashed on startup: %s", e)
        raise
