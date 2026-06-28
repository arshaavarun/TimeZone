"""Home page route."""
from flask import render_template

from timezone import app
from timezone.config import *          # noqa: F401,F403
from timezone.database import get_db
from timezone.services import *        # noqa: F401,F403



@app.route("/")
def home():
    db = get_db()
    cid = current_client_id(db)
    return render_template("home.html", progress=monthly_progress(db, cid))
