from flask import Flask

from analytics import analytics_bp
from config import Config
from db import close_session
from main import main_bp
from predictions import predictions_bp


def create_app():
    """
    Application factory instead of a bare module-level `app = Flask(...)`.

    Why this pattern here specifically: 6b and 6c are each going to add
    their own blueprint (analytics, predictions). A factory function is
    the standard way to register a growing set of blueprints cleanly, and
    it also means the app can be imported and re-created in a test file
    later without side effects firing at import time. For a one-route app
    it's overkill; for where this is headed in the next two sub-stages,
    it's the right amount of structure up front.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    app.register_blueprint(main_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(predictions_bp)

    # Ensures SessionLocal.remove() runs after every request (success or
    # error), so DB connections always return to the pool.
    app.teardown_appcontext(close_session)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
