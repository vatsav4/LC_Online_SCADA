"""
Line-2 torque dashboard.

Data (both on the Line-2 SQL Server, reachable only on port 49561):
  dbo.Station_Mapping      vehicle (VC / MAT) at each station
  dbo.Torques_Actual_Data  Set / Actual counts and bypass per wrench, written by the
                           WinCC script wincc/Torques_To_SQL_Action.vbs
([MAIN] source = logdump switches to the older smartapp log table, see logdump.py.)

Which wrenches belong to a station, and where each torque point is on the
chassis picture, comes from the station layouts (layouts.py), edited on the
station page by logged-in line managers (auth.py, manage_users.py).

A background thread polls SQL every few seconds and keeps the latest snapshot
in memory; pages and JSON endpoints only read that snapshot.
"""

import configparser
import copy
import logging
import os
import threading
import time
from datetime import datetime

from flask import (Flask, abort, jsonify, redirect, render_template, request, send_file, session,
                   url_for)

import auth
import layouts
import logdump
import torques

# ================= CONFIG =================
# Real credentials belong in config.ini (gitignored), not in this file.
# See config.ini.example for the format.

_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(os.path.dirname(__file__), "config.ini"))


def _get(section, key, default):
    try:
        return _cfg[section][key]
    except KeyError:
        return default


LINE_DB = {
    "server": _get("SQL_LINE", "server", "172.25.208.39"),
    "port": _get("SQL_LINE", "port", "49561"),
    "database": _get("SQL_LINE", "database", "Industry4_157"),
    "username": _get("SQL_LINE", "username", "CHANGE_ME"),
    "password": _get("SQL_LINE", "password", "CHANGE_ME"),
}

ODBC_DRIVER = _get("ODBC", "driver", "ODBC Driver 18 for SQL Server")
POLL_INTERVAL = float(_get("MAIN", "poll_interval", "2"))
WEB_PORT = int(_get("MAIN", "web_port", "5001"))  # 5000 is the Line-3 andon dashboard
LINE_TITLE = _get("MAIN", "line_title", "Line - 2 | Assembly Shop")
DEFAULT_IMAGE = _get("MAIN", "chassis_image", "chassis-top.svg")  # used until a station picks one
DEMO_MODE = _get("MAIN", "demo_mode", "false").strip().lower() in ("1", "true", "yes", "on")
SOURCE = _get("MAIN", "source", "torques").strip().lower()  # "torques" or "logdump"
SECRET_KEY = _get("MAIN", "secret_key", "").strip()

# Only for source = logdump: only read log rows for this shop_id_id.
SHOP_ID = _get("FILTER", "shop_id", "").strip() or None

# ================= LOGGING =================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LINE2_DASHBOARD")

# ================= SHARED STATE =================
# raw = stations straight from SQL; stations = raw with the layouts applied.

state_lock = threading.Lock()
state = {
    "raw": {},
    "stations": {},  # {station_no: {station, vc_number, mat_number, status, image, tools: [...]}}
    "known_tools": [],  # every wrench number seen in the data (for the layout editor)
    "updated_at": None,
    "db_ok": False,
}


# ================= SQL =================

def connect(cfg):
    import pyodbc

    # SQL Server takes the port after a COMMA: SERVER=172.25.208.39,49561
    return pyodbc.connect(
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={cfg['server']},{cfg['port']};"
        f"DATABASE={cfg['database']};"
        f"UID={cfg['username']};"
        f"PWD={cfg['password']};"
        f"Encrypt=yes;TrustServerCertificate=yes;",
        timeout=5,
    )


def load_raw():
    """Read the configured source. Returns (raw_stations, known_tool_numbers)."""
    if SOURCE == "logdump":
        if DEMO_MODE:
            import demo_data
            rows = demo_data.station_rows()
        else:
            conn = connect(LINE_DB)
            try:
                rows = logdump.fetch_station_rows(conn, SHOP_ID)
            finally:
                conn.close()
        raw = logdump.build_stations(rows)
        known = sorted({t["tag"] for st in raw.values() for t in st["tools"]}, key=logdump._tag_key)
        return raw, known

    if DEMO_MODE:
        import demo_data
        mapping, torque_rows = demo_data.mapping_rows(), demo_data.torque_rows()
    else:
        conn = connect(LINE_DB)
        try:
            mapping, torque_rows = torques.fetch(conn)
        finally:
            conn.close()
    return torques.build_stations(mapping, torque_rows, layouts.load()), torques.all_tool_numbers(torque_rows)


def publish(raw, known=None, db_ok=True):
    """Apply the current layouts to raw data and make it the live snapshot."""
    stations = layouts.apply(copy.deepcopy(raw), layouts.load(), DEFAULT_IMAGE)
    with state_lock:
        state["raw"] = raw
        state["stations"] = stations
        if known is not None:
            state["known_tools"] = known
        state["updated_at"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        state["db_ok"] = db_ok


def poll_once():
    try:
        raw, known = load_raw()
        publish(raw, known)
    except Exception as e:
        logger.error(f"Poll failed: {e}")
        with state_lock:
            state["db_ok"] = False


def poll_loop():
    while True:
        poll_once()
        time.sleep(POLL_INTERVAL)


# ================= FLASK APP =================

app = Flask(__name__)
app.config.update(
    SECRET_KEY=auth.secret_key(SECRET_KEY),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,  # chassis picture uploads
)


@app.context_processor
def _globals():
    return {"line_title": LINE_TITLE, "demo_mode": DEMO_MODE,
            "user": auth.current_user(), "csrf_token": auth.csrf_token()}


def _snapshot():
    with state_lock:
        return dict(state["stations"]), state["db_ok"], state["updated_at"]


def _summary(stations):
    return [
        {"id": st["station"], "status": st["status"], "mat_number": st["mat_number"],
         "ok": sum(t["status"] == "OK" for t in st["tools"]), "total": len(st["tools"])}
        for st in (stations[n] for n in sorted(stations))
    ]


@app.route("/")
def index():
    stations, db_ok, updated_at = _snapshot()
    return render_template("index.html", stations=_summary(stations), db_ok=db_ok, updated_at=updated_at)


@app.route("/station/<int:station_id>")
def station(station_id):
    stations, db_ok, updated_at = _snapshot()
    if station_id not in stations and stations:
        abort(404)
    return render_template("station.html", station_id=station_id, st=stations.get(station_id),
                           last_station=max(stations, default=station_id),
                           db_ok=db_ok, updated_at=updated_at)


@app.route("/chassis/<name>")
def chassis_image(name):
    path = layouts.image_path(name)
    if not path:
        abort(404)
    return send_file(path, max_age=3600)


# ---------- login ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    next_url = request.values.get("next") or url_for("index")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("index")
    if request.method == "POST":
        auth.check_form_csrf()
        username = request.form.get("username", "").strip()
        if auth.check_login(username, request.form.get("password", "")):
            session.clear()
            session["user"] = username
            logger.info(f"Login: {username}")
            return redirect(next_url)
        error = "Wrong username or password."
    return render_template("login.html", error=error, next_url=next_url, db_ok=_snapshot()[1])


@app.route("/logout", methods=["POST"])
def logout():
    auth.check_form_csrf()
    session.clear()
    next_url = request.form.get("next") or ""
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = url_for("index")
    return redirect(next_url)


# ---------- JSON API ----------

@app.route("/api/status")
def api_status():
    stations, db_ok, updated_at = _snapshot()
    return jsonify({"stations": _summary(stations), "db_ok": db_ok, "updated_at": updated_at})


@app.route("/api/station/<int:station_id>")
def api_station(station_id):
    stations, db_ok, updated_at = _snapshot()
    if station_id not in stations:
        abort(404)
    return jsonify({**stations[station_id], "db_ok": db_ok, "updated_at": updated_at,
                    "can_edit": bool(auth.current_user())})


@app.route("/api/editor")
@auth.manager_required
def api_editor():
    """What the layout editor needs: wrench numbers, which station has each, and pictures."""
    with state_lock:
        known = list(state["known_tools"])
        stations = dict(state["stations"])
    assigned = {t["tag"]: n for n, st in stations.items() for t in st["tools"]}
    return jsonify({"tools": sorted(set(known) | set(assigned), key=logdump._tag_key),
                    "assigned": assigned, "images": layouts.list_images()})


@app.route("/api/layout/<int:station_id>", methods=["POST"])
@auth.manager_required
def api_save_layout(station_id):
    if not 1 <= station_id <= 999:
        abort(404)
    try:
        saved = layouts.save(station_id, request.get_json(silent=True), auth.current_user())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    logger.info(f"Layout of station {station_id} saved by {auth.current_user()}")
    with state_lock:
        raw = state["raw"]
    if SOURCE == "torques":
        poll_once()  # wrench list per station comes from the layout - rebuild now
    else:
        publish(raw, db_ok=_snapshot()[1])
    return jsonify({"ok": True, "layout": saved})


@app.route("/api/chassis-images", methods=["POST"])
@auth.manager_required
def api_upload_image():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No file received."}), 400
    try:
        name = layouts.save_upload(file.filename, file.read())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    logger.info(f"Chassis image {name} uploaded by {auth.current_user()}")
    return jsonify({"ok": True, "name": name, "images": layouts.list_images()})


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
