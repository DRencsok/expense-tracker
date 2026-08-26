from flask import Blueprint, render_template, request, url_for, session, redirect, flash
from app.database import get_db
from app.auth import hash_password, verify_password

main = Blueprint("main", __name__)


@main.route("/")
def index():
    db = get_db()
    return render_template("index.html", db=db)

@main.route("/login")
def login():
    return render_template("login.html")

@main.route("/register", methods=["GET", "POST"])
def register():
    # Handle user registration
    db = get_db()
    if request.method == "POST":
        if not request.form["username"] or not request.form["password"]:
            return render_template("register.html", error="Please fill in all fields.")
        if request.form["password"] != request.form["confirm_password"]:
            return render_template("register.html", error="Passwords do not match.")
        if db.execute ("SELECT id FROM users WHERE username = ?", (request.form["username"],)).fetchone() is not None:
            return render_template("register.html", error="Username already exists.")
    
        username = request.form["username"]
        password = request.form["password"]
        hashed_password = hash_password(password)

        # Save user to database
        db.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        db.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("main.login"))
    else:
        return render_template("register.html")

@main.route("/analytics")
def analytics():
    db = get_db()
    return render_template("analytics.html", db=db)

@main.route("/calendar")
def calendar():
    db = get_db()
    return render_template("calendar.html", db=db)

@main.route("/profile")
def profile():
    db = get_db()
    return render_template("profile.html", db=db)

@main.route("/settings")
def settings():
    db = get_db()
    return render_template("settings.html", db=db)

@main.route("/logout", methods=["POST"])
def logout():
    db = get_db()
    if request.method == "POST":
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for("main.login"))
    return render_template("logout.html", db=db)