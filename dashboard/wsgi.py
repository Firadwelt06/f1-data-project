try:
    from .app import create_app
except ImportError:  # pragma: no cover - supports local script execution
    from app import create_app

app = create_app()
