from functools import wraps

from flask import redirect, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped_view

def hash_password(password):
    return generate_password_hash(password)

def verify_password(hashed_password, password):
    return check_password_hash(hashed_password, password)
