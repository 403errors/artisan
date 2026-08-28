def main() -> None:
    """Local/Cloud Run entrypoint — runs the orchestrator FastAPI app (see app.py)."""
    import os

    import uvicorn

    uvicorn.run(
        "artisan_agents.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
