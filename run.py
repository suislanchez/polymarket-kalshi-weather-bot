#!/usr/bin/env python3
"""Run the trading bot backend server."""
import os
import uvicorn
from backend.models.database import init_db

if __name__ == "__main__":
    print("Initializing database...")
    init_db()

    port = int(os.environ.get("PORT", 8765))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"Starting server on http://{host}:{port}")
    print(f"API docs available at http://localhost:{port}/docs")

    uvicorn.run(
        "backend.api.main:app",
        host=host,
        port=port,
        reload=os.environ.get("RAILWAY_ENVIRONMENT") is None
    )
