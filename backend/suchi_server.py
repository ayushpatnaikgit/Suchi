"""Entry point for the Suchi API server (used by PyInstaller sidecar)."""

import uvicorn


def main():
    uvicorn.run("suchi.api:app", host="127.0.0.1", port=9876, log_level="info")


if __name__ == "__main__":
    main()
