from flask import Blueprint, render_template
from sqlalchemy import text

from db import get_session

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    session = get_session()

    stats = session.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM races)        AS race_count,
                (SELECT COUNT(*) FROM drivers)       AS driver_count,
                (SELECT COUNT(*) FROM constructors)  AS constructor_count,
                (SELECT MIN(year) FROM races)        AS first_year,
                (SELECT MAX(year) FROM races)        AS last_year
            """
        )
    ).mappings().first()

    return render_template("index.html", stats=stats)
