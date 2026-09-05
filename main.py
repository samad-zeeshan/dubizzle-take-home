"""Entry point for uvicorn: `uv run uvicorn main:app --reload`."""

from dubizzle_assistant.api.app import create_app

app = create_app()
