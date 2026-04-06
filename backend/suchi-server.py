"""Entry point for the bundled Suchi backend server (PyInstaller)."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("suchi.api:app", host="127.0.0.1", port=9876, log_level="warning")
