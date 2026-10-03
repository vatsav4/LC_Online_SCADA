"""
Line-manager login for editing station layouts.

Accounts live in data/users.json (not in git) with hashed passwords, managed
from the command line on the dashboard PC:

    python manage_users.py add <username>       # asks for the password
    python manage_users.py remove <username>
    python manage_users.py list

Everyone can view the dashboard; only logged-in managers can change layouts.
"""
import functools
import hmac
import json
import os
import secrets
import time

from flask import abort, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from layouts import DATA_DIR

USERS_FILE = os.path.join(DATA_DIR, "users.json")
SECRET_FILE = os.path.join(DATA_DIR, "secret_key")


def load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_users(users):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_FILE)


def set_password(username, password):
    users = load_users()
    users[username] = {"password_hash": generate_password_hash(password)}
    save_users(users)


def check_login(username, password):
    user = load_users().get(username)
    if user and check_password_hash(user["password_hash"], password):
        return True
    time.sleep(1)  # slow down password guessing
    return False


def secret_key(configured):
    """Flask secret key: from config.ini if set, else generated once and kept in data/."""
    if configured:
        return configured
    try:
        with open(SECRET_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        key = secrets.token_hex(32)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SECRET_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        return key


def current_user():
    return session.get("user")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def _csrf_ok():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf") or ""
    return bool(sent) and bool(expected) and hmac.compare_digest(sent, expected)


def manager_required(view):
    """For JSON endpoints that change things: must be logged in and send the CSRF token."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify({"error": "Please log in as a line manager."}), 401
        if not _csrf_ok():
            return jsonify({"error": "Session expired - reload the page and try again."}), 403
        return view(*args, **kwargs)
    return wrapper


def check_form_csrf():
    if not _csrf_ok():
        abort(400)
