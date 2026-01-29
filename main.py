#!/usr/bin/env python3
"""
Main entry point for the backend server.
Run with: uv run main.py
"""

import uvicorn


def main():
    """Run the FastAPI backend server."""
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["backend"],
    )


if __name__ == "__main__":
    main()
