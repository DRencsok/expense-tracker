from flask import Blueprint, render_template
from app.database import get_db

main = Blueprint("main", __name__)


@main.route("/")
def homepage():
    db = get_db()
    return render_template("index.html", db=db)