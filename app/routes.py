import os
import json
from flask import Blueprint, jsonify, render_template, request, url_for, session, redirect, flash
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, OpenAIError, RateLimitError
from app.database import get_db
from app.auth import hash_password, login_required, verify_password
from datetime import datetime
import calendar as cal

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
        if len(password) < 8:
            return render_template("register.html", error="Password must be at least 8 characters long")
    
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
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify(error="OPENAI_API_KEY is not configured."), 503

    db = get_db()
    rows = db.execute(
        """
        SELECT transaction_type, category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ? AND spent_at >= date('now', 'start of month')
        GROUP BY transaction_type, category
        ORDER BY total DESC
        """,
        (session["user_id"],),
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
                "You are a practical personal finance assistant. "
                "Analyze this user's current-month transaction summary.\n\n"
                f"{summary}\n\n"
                "Give exactly 3 short, specific recommendations. "
                "Do not invent facts. "
                "Mention when there is not enough data. "
                "This is general education, not financial advice."
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "finance_recommendations",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "recommendations": {
                                "type": "array",
                                "minItems": 3,
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {
                                            "type": "string"
                                        },
                                        "description": {
                                            "type": "string"
                                        },
                                        "action": {
                                            "type": "string"
                                        }
                                    },
                                    "required": [
                                        "title",
                                        "description",
                                        "action"
                                    ],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["recommendations"],
                        "additionalProperties": False
                    }
                }
            }
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

    #Get dates
    now = datetime.now()
    year = request.args.get("year", now.year, type = int)
    month = request.args.get("month", now.month, type = int)

    selected_month = f"{year:04d}-{month:02d}"

    transactions = db.execute(
        """
        SELECT transaction_type, spent_at, SUM(amount) as total
          FROM expenses
         WHERE user_id = ?
           AND strftime('%Y-%m', spent_at) = ?
         GROUP BY spent_at, transaction_type
         ORDER BY spent_at 
        """,
        (session['user_id'],selected_month),
    ).fetchall()

    #The calendar
    first_weekday, number_of_days = cal.monthrange(year, month)

    days = []
    for _ in range(first_weekday):
        days.append(None)
    for day in range(1, number_of_days + 1):
        days.append(day)

    while len(days) not in (35, 42):
        days.append(None)

    #The day combined with expenses
    transactions_by_day = {}
    for day in days:
        if day is None:
            continue
        transactions_by_day[day] = {
            "income": 0,
            "expense": 0,
        }

        for transaction in transactions:
            date_day = int(transaction["spent_at"][-2:])

            if date_day == day:
                transactions_by_day[day][transaction["transaction_type"]] = transaction["total"]

    #Previous month
    if month == 1:
        previous_month = 12
        previous_year = year - 1
    else:
        previous_month = month - 1
        previous_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    month_name = datetime(year, month, 1).strftime("%B")

    return render_template("calendar.html", days=days, 
                           transactions_by_day=transactions_by_day,
                           year=year,
                           month=month,
                           previous_year=previous_year,
                           previous_month=previous_month,
                           next_year=next_year,
                           next_month=next_month,
                           month_name=month_name
                           )

@main.route("/profile")
@login_required
def profile():
    db = get_db()
    total_expenses = db.execute(
        """
        SELECT
            COUNT(id) 
            FROM expenses 
            WHERE user_id = ?
        """, (session['user_id'],),
    ).fetchone()[0]

    return render_template("profile.html", amount=total_expenses)

@main.route("/settings", methods=["POST", "GET"],)
@login_required
def settings():
    db = get_db()
    #Check for user input
    if request.method == "POST":

        #Check whick form
        if "change_password" in request.form:    
            if not request.form["oldPassword"] or not request.form["newPassword"]:
                return render_template("settings.html", error="Fields cannot be empty")
            old_password = request.form["oldPassword"]
            new_password = request.form["newPassword"]

            if len(new_password) < 8:
                return render_template("setting.html", error="Password must be at least 8 characters long")
            user_password = db.execute("""
            SELECT password
            FROM users
            WHERE id = ?
            """,(session['user_id'],)).fetchone()

            #Check corectness of old password
            if not verify_password(user_password["password"], old_password):
                return render_template("settings.html", error="Old password incorrect")
            
            new_hash = hash_password(new_password)

            db.execute("UPDATE users SET password = ? WHERE id = ?",(new_hash, session['user_id'],))
            db.commit()
            flash("Change was successful!", "success")
            return redirect(url_for("main.index"))

        elif "change_username" in request.form:
            if not request.form["newUsername"]:
                return render_template("settings.html", error="Field cannot be empty")
            new_username = request.form["newUsername"]

            if db.execute ("SELECT id FROM users WHERE username = ?", (new_username,)).fetchone() is not None:
                        return render_template("register.html", error="Username already exists.")

            db.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, session['user_id'],))
            db.commit()
            session["username"] = new_username
            
            flash("Change was successful!", "success")
            return redirect(url_for("main.index"))

        
    return render_template("settings.html")

@main.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))