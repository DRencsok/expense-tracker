import os
import json
from flask import Blueprint, jsonify, render_template, request, url_for, session, redirect, flash
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, OpenAIError, RateLimitError
from app.database import get_db
from app.auth import hash_password, login_required, verify_password

main = Blueprint("main", __name__)


@main.route("/", methods=["GET", "POST"])
def index():
    db = get_db()

    if request.method == "POST":
        category = request.form["category"]
        transaction_type = request.form["transaction_type"]
        amount = request.form["amount"]
        description = request.form["description"]
        if not category or not transaction_type or not amount:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("main.index"))

        db.execute(
            "INSERT INTO expenses (user_id, category, transaction_type, amount, description) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], category, transaction_type, amount, description),
        )
        db.commit()
        flash("Transaction added successfully!", "success")
        return redirect(url_for("main.index"))

    if session.get("user_id") is None:
        return render_template("index.html")

    user_id = session["user_id"]
    spending = db.execute(
        """
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ? AND transaction_type = 'expense'
        GROUP BY category
        ORDER BY total DESC
        """,
        (user_id,),
    ).fetchall()
    recent_transactions = db.execute(
        """
        SELECT category, transaction_type, amount, description, spent_at
        FROM expenses
        WHERE user_id = ?
        ORDER BY spent_at DESC, id DESC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()
    totals = db.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'income' THEN amount ELSE 0 END), 0) AS income,
            COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END), 0) AS expenses
        FROM expenses
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return render_template(
        "index.html",
        categories=[row["category"] for row in spending],
        totals=[float(row["total"]) for row in spending],
        recent_transactions=recent_transactions,
        income_total=float(totals["income"]),
        expense_total=float(totals["expenses"]),
    )

@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Handle login logic
        db = get_db()
        if not request.form["username"] or not request.form["password"]:
            return render_template("login.html", error="Please fill in all fields.")
        user = db.execute("SELECT * FROM users WHERE username = ?", (request.form["username"],)).fetchone()
        if user is None or not verify_password(user["password"], request.form["password"]):
            return render_template("login.html", error="Invalid username or password.")
        # Store user information in session
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("main.index"))
    else:
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

@main.route("/analytics", methods=["GET", "POST"])
@login_required
def analytics():
    db = get_db()
    if request.method == "POST":
        # Handle transaction deletion
        transaction_id = request.form.get("transaction_id")
        if transaction_id:
            db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (transaction_id, session["user_id"]))
            db.commit()
            flash("Transaction deleted successfully!", "success")
        return redirect(url_for("main.analytics"))
    spending = db.execute(
        """
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ? AND transaction_type = 'expense'
        GROUP BY category
        ORDER BY total DESC
        """,
        (session["user_id"],),
    ).fetchall()
    transactions = db.execute(
        """
        SELECT id, category, transaction_type, amount, description, spent_at
        FROM expenses
        WHERE user_id = ?
        ORDER BY spent_at DESC, id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template(
        "analytics.html",
        categories=[row["category"] for row in spending],
        totals=[float(row["total"]) for row in spending],
        transactions=transactions,
        transaction_dates=[row["spent_at"] for row in transactions],
        transaction_amounts=[
            float(row["amount"])
            if row["transaction_type"] == "income"
            else -float(row["amount"])
            for row in transactions
        ],
    )


@main.route("/analytics/advice", methods=["POST"])
@login_required
def analytics_advice():
    #use openai api to get advice
    payload = request.get_json(silent=True) or {}
    period = payload.get("period", "weekly") if request.is_json else "weekly"
    if period not in {"weekly", "monthly"}:
        return jsonify(error="Choose weekly or monthly analysis."), 400

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify(error="OPENAI_API_KEY is not configured."), 503

    days = 7 if period == "weekly" else 30
    db = get_db()
    rows = db.execute(
        """
        SELECT transaction_type, category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ? AND spent_at >= date('now', ?)
        GROUP BY transaction_type, category
        ORDER BY total DESC
        """,
        (session["user_id"], f"-{days - 1} days"),
    ).fetchall()

    summary = [
        {
            "type": row["transaction_type"],
            "category": row["category"],
            "total": round(float(row["total"]), 2),
        }
        for row in rows
    ]
    client = OpenAI(api_key=api_key)
    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=(
                "You are a practical personal finance assistant. Analyze this user's "
                f"""
                    Analyze this user's {period} transaction summary:

                    {summary}

                    Give exactly 3 short, specific recommendations.

                    Return ONLY valid JSON in this format:

                    {{
                        "recommendations": [
                            {{
                                "title": "Short recommendation title",
                                "description": "Short explanation",
                                "action": "One practical action"
                            }}
                        ]
                    }}

                    Do not invent facts.
                    Mention when there is not enough data.
                    This is general education, not financial advice.
                    """
            ),
        )
    except AuthenticationError:
        return jsonify(error="The OpenAI API key was rejected. Check that it is active and restart Flask."), 502
    except RateLimitError:
        return jsonify(error="The OpenAI API quota or rate limit was reached. Check your account billing and limits."), 429
    except APIConnectionError:
        return jsonify(error="Could not connect to the OpenAI API. Check your internet connection."), 502
    except APIStatusError as error:
        return jsonify(error=f"OpenAI returned an API error (status {error.status_code})."), 502
    except OpenAIError:
        return jsonify(error="The advice service is temporarily unavailable."), 502
    
    try:
        data = json.loads(response.output_text)
    except json.JSONDecodeError:
        return jsonify(error="OpenAI returned an invalid recommendation format."), 502
    return jsonify(advice=data)

@main.route("/calendar")
@login_required
def calendar():
    db = get_db()
    return render_template("calendar.html", db=db)

@main.route("/profile")
@login_required
def profile():
    db = get_db()
    return render_template("profile.html", db=db)

@main.route("/settings")
@login_required
def settings():
    db = get_db()
    return render_template("settings.html", db=db)

@main.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))