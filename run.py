#!/usr/bin/env python3
"""Run the trading bot backend server."""
import uvicorn
from backend.models.database import init_db

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Starting server on http://localhost:8000")
    print("API docs available at http://localhost:8000/docs")
    uvicorn.run(
        "backend.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
