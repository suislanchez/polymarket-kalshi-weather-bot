"""API package exports.

Importing dependency-light schema modules should not require FastAPI/SQLAlchemy
runtime dependencies.  Load the FastAPI app lazily only when callers request it.
"""


def __getattr__(name):
    if name == "app":
        from backend.api.main import app

        return app
    raise AttributeError(name)


__all__ = ["app"]
