"""
Line-2 torque dashboard.

Tables on the Line-2 SQL Server (reachable only on port 49561):
  dbo.Station_Mapping      StationNumber, VC_Number, MAT_Number   (vehicle at each station)
  dbo.Torques_Actual_Data  T_No, T_Name, Set_Counts, Actual_Counts, Active_Bypass
                           (one row per wrench, written by wincc/Torques_To_SQL_Action.vbs)
  dbo.S3_Controls_Data     Station_No, Tag_Name, Status, Changed_At
                           (one row per S3 control, 1 = NOT OK / 0 = OK,
                            written by wincc/S3_Controls_To_SQL_Action.vbs)

Which wrenches a station shows, and where each circle sits on the chassis
picture, is written in that station's template: templates/station_<n>.html
    {% set chassis_image = "IMG_2.jpg" %}
    {% set tools = [ {"t_no": "T18", "x": 16, "y": 33}, ... ] %}
The name on each box is typed in the template too ("name"); SQL only supplies the
counts and bypass state. A station with S3 controls also lists them there:
    {% set s3_controls = [ {"tag": "Inversion_Light_Curtain_LH", "name": "..."}, ... ] %}
The app reads that list from the template itself, so the station page and its
tile on the overview always agree.

Line managers (accounts in config.ini [MANAGERS]) can log in, click "Edit
positions" on a station page, drag the circles and Save: the new x / y are
written straight back into that station's template file (old copy kept as
station_<n>.html.bak). Make a password hash with:  python app.py hash-password

A background thread reads both tables every few seconds and keeps the latest
values in memory; pages and JSON endpoints only read that snapshot.
"""

import configparser
import getpass
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
from datetime import datetime

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from jinja2 import TemplateSyntaxError, nodes
from werkzeug.security import check_password_hash, generate_password_hash

# ================= CONFIG =================
# Real credentials belong in config.ini (gitignored), not in this file.
# See config.ini.example for the format.

_cfg = configparser.ConfigParser(interpolation=None)  # passwords / hashes may contain % or $
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
TOTAL_STATIONS = int(_get("MAIN", "total_stations", "17"))
DEFAULT_IMAGE = "IMG_1.jpg"  # static/chassis/ picture for a station template that doesn't set one
DEMO_MODE = _get("MAIN", "demo_mode", "false").strip().lower() in ("1", "true", "yes", "on")
# Signs the login cookie. Empty = random at every start (managers just log in again after a restart).
SECRET_KEY = _get("MAIN", "secret_key", "").strip() or secrets.token_hex(32)
# username = password hash (from: python app.py hash-password)
MANAGERS = dict(_cfg["MANAGERS"]) if _cfg.has_section("MANAGERS") else {}
# Changes at every start: pages that see a new value reload themselves, so unattended
# screens (the digital standee) pick up an updated dashboard without anyone touching them.
APP_VERSION = str(int(time.time()))

# ================= LOGGING =================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LINE2_DASHBOARD")

# ================= SHARED STATE =================
# Written only by poll_loop(), read only by routes/API handlers.

state_lock = threading.Lock()
state = {
    "mapping": {},   # {station_no: {"vc": .., "mat": ..}}
    "torques": {},   # {"T1": {"name": .., "set": .., "actual": .., "bypass": bool}}
    "s3": {},        # {"INVERSION_OVER_TRAVEL": {"value": 0 / 1 / None, "changed": datetime}}
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


def _num(value):
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def fetch_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT StationNumber, VC_Number, MAT_Number FROM dbo.Station_Mapping")
    mapping = {int(r[0]): {"vc": str(r[1] or "").strip(), "mat": str(r[2] or "").strip()}
               for r in cur.fetchall()}
    cur.execute("SELECT T_No, T_Name, Set_Counts, Actual_Counts, Active_Bypass FROM dbo.Torques_Actual_Data")
    torques = {str(r[0]).strip().upper(): {"name": str(r[1] or "").strip(), "set": _num(r[2]),
                                           "actual": _num(r[3]), "bypass": r[4] in (True, 1, "1")}
               for r in cur.fetchall() if r[0]}
    return mapping, torques, fetch_s3(conn)


_s3_failed = False  # log a missing / broken S3 table once, not every poll


def fetch_s3(conn):
    """S3 controls; on its own so a missing S3 table never stops the torque data."""
    global _s3_failed
    try:
        cur = conn.cursor()
        cur.execute("SELECT Tag_Name, Status, Changed_At FROM dbo.S3_Controls_Data")
        rows = cur.fetchall()
    except Exception as e:
        if not _s3_failed:
            logger.error(f"S3_Controls_Data not readable (S3 controls show NO DATA): {e}")
        _s3_failed = True
        return {}
    _s3_failed = False
    return {str(r[0]).strip().upper(): {"value": None if r[1] is None else int(bool(r[1])), "changed": r[2]}
            for r in rows if r[0]}


def demo_tables():
    """Sample data for demo_mode = true (no database). T2 / T3 count up so the page looks live."""
    tick = int(time.time() // 3)
    mapping = {1: ("55072654300R", "MAT784062TFJ12788"), 2: ("55072654300R", "MAT784062TFJ12787"),
               4: ("55329329000R", "MAT805017TFJ12785"), 5: ("55131252100R", "MAT513357TFJ12784"),
               8: ("55131252100R", "MAT513357TFJ12781"), 10: ("55131252100R", "MAT513357TFJ12779")}
    torques = {"T1": ("SG Tightening", 5, 5, 0), "T2": ("Tail Tightening", 5, tick % 7, 0),
               "T3": ("Nylon Tightening", 5, (tick + 3) % 7, 0), "T18": ("ARB bolt fitment", 4, 0, 0),
               "T19": ("Axle brake hose", 1, 8, 0), "T23": ("Front/rear ARB", 4, 0, 0),
               "T26": ("Brake hose adapter", 2, 2, 1), "T37": ("Steering return line", 2, 10, 0),
               "T38": ("Urea tank fitment", 6, 6, 1), "T39": ("EGP clamp bolt", 2, 11, 1),
               "T40": ("Air tank bracket", 4, 10, 1),
               "T4": ("Not used on this model", 0, 0, 0)}   # Set Count 0: hidden on station 2
    since = datetime.now().replace(microsecond=0)
    # light curtains: 1 = OK (ok_value 1 in station_7.html); LH trips now and then
    s3 = {"INVERSION_LIGHT_CURTAIN_LH": {"value": int(tick % 5 != 0), "changed": since},
          "INVERSION_LIGHT_CURTAIN_RH": {"value": 1, "changed": since.replace(hour=6, minute=0, second=0)},
          "INVERSION_OVER_TRAVEL": {"value": 0, "changed": since.replace(hour=6, minute=0, second=0)}}
    return ({n: {"vc": vc, "mat": mat} for n, (vc, mat) in mapping.items()},
            {t: {"name": n, "set": s, "actual": a, "bypass": bool(b)} for t, (n, s, a, b) in torques.items()},
            s3)


def poll_once():
    try:
        if DEMO_MODE:
            mapping, torques, s3 = demo_tables()
        else:
            conn = connect(LINE_DB)
            try:
                mapping, torques, s3 = fetch_tables(conn)
            finally:
                conn.close()
        with state_lock:
            state["mapping"], state["torques"], state["s3"] = mapping, torques, s3
            state["updated_at"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            state["db_ok"] = True
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
    TEMPLATES_AUTO_RELOAD=True,  # edited station templates show up on refresh
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)


# ---------- station templates ----------

def station_template(station_id):
    name = f"station_{station_id}.html"
    if os.path.exists(os.path.join(app.root_path, "templates", name)):
        return name
    return "station_generic.html"


_template_cache = {}  # template file -> (mtime, config)
S3_PICTURES = ("area_scanner", "light_curtain", "over_travel", "sensor")  # drawings in static/s3.js


def _s3_picture(tag, picture):
    if picture in S3_PICTURES:
        return picture
    tag = tag.upper()
    if "SCANNER" in tag:
        return "area_scanner"
    if "LIGHT_CURTAIN" in tag:
        return "light_curtain"
    if "OVER_TRAVEL" in tag or "OVERTRAVEL" in tag:
        return "over_travel"
    return "sensor"


def station_config(station_id):
    """The `chassis_image`, `tools` and `s3_controls` set at the top of templates/station_<n>.html.

    Re-read automatically when the template file changes, so editing T_Nos
    needs no restart (only a browser refresh). A template with a mistake in it
    gives an "error" instead of breaking the home page.
    """
    name = station_template(station_id)
    path = os.path.join(app.root_path, "templates", name)
    mtime = os.path.getmtime(path)
    cached = _template_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    found = {}
    try:
        with open(path, encoding="utf-8") as f:
            tree = app.jinja_env.parse(f.read())
    except TemplateSyntaxError as e:
        error = f"{name} line {e.lineno}: {e.message}"
        logger.error(f"Template mistake, station {station_id} shows nothing until it is fixed: {error}")
        config = {"chassis_image": DEFAULT_IMAGE, "tools": [], "s3_controls": [], "error": error}
        _template_cache[path] = (mtime, config)
        return config
    for node in tree.find_all(nodes.Assign):
        if isinstance(node.target, nodes.Name) and node.target.name in ("tools", "chassis_image", "s3_controls"):
            try:
                found[node.target.name] = node.node.as_const()
            except nodes.Impossible:
                logger.error(f"{name}: '{node.target.name}' must be written out literally")

    tools = []
    for t in found.get("tools") or []:
        if not isinstance(t, dict) or not str(t.get("t_no", "")).strip():
            logger.error(f"{name}: every tool needs a t_no, skipped {t!r}")
            continue
        x, y = t.get("x"), t.get("y")
        placed = isinstance(x, (int, float)) and isinstance(y, (int, float))
        tools.append({"t_no": str(t["t_no"]).strip().upper(),
                      "name": str(t.get("name") or "").strip(),
                      "x": min(100, max(0, x)) if placed else None,
                      "y": min(100, max(0, y)) if placed else None})
    s3_controls = []
    for c in found.get("s3_controls") or []:
        tag = str(c.get("tag", "")).strip() if isinstance(c, dict) else ""
        if not tag:
            logger.error(f"{name}: every S3 control needs a tag, skipped {c!r}")
            continue
        place = c.get("place") if c.get("place") in ("top", "bottom") else (
            "bottom" if tag.upper().endswith(("_RH", "RH")) else "top")   # RH side drawn below the chassis
        s3_controls.append({"tag": tag.upper(), "name": str(c.get("name") or "").strip() or tag.replace("_", " "),
                            "picture": _s3_picture(tag, c.get("picture")), "place": place,
                            # tag value that means OK: 0 normally, 1 for signals like the inversion light curtains
                            "ok_value": 1 if c.get("ok_value") == 1 else 0})
    config = {"chassis_image": found.get("chassis_image") or DEFAULT_IMAGE, "tools": tools,
              "s3_controls": s3_controls, "error": None}
    _template_cache[path] = (mtime, config)
    return config


def _since(changed):
    if not isinstance(changed, datetime):
        return ""
    return f"{changed:%H:%M:%S}" if changed.date() == datetime.now().date() else f"{changed:%d-%m %H:%M}"


def build_station(station_id, mapping, torques, s3=None):
    config = station_config(station_id)
    vehicle = mapping.get(station_id, {})
    tools = []
    for t in config["tools"]:
        row = torques.get(t["t_no"])
        if row is None or row["set"] is None or row["actual"] is None:
            status = "PENDING"
        else:
            status = "OK" if row["actual"] >= row["set"] else "NOT OK"
        tools.append({
            # Set Count 0 = this wrench isn't used for the vehicle model now at the station:
            # not shown and not counted (the station page still lists it while a manager edits positions)
            "hidden": row is not None and row["set"] == 0,
            "tag": t["t_no"],
            "label": t["name"] or t["t_no"],  # name typed in the station template
            "x": t["x"], "y": t["y"],
            "set": (row or {}).get("set"),
            "actual": (row or {}).get("actual"),
            # bypass state is still read from SQL (Active_Bypass) but not shown for now
            "status": status,
        })
    controls = []
    for c in config["s3_controls"]:
        row = (s3 or {}).get(c["tag"]) or {}
        value = row.get("value")
        controls.append({**c, "status": "PENDING" if value is None else ("OK" if value == c["ok_value"] else "NOT OK"),
                         "since": _since(row.get("changed"))})
    checks = [t for t in tools if not t["hidden"]] + controls
    return {
        "station": station_id,
        "vc_number": vehicle.get("vc", ""),
        "mat_number": vehicle.get("mat", ""),
        "image": config["chassis_image"],
        "tools": tools,
        "s3": controls,
        "error": config["error"],
        "status": "idle" if not checks else ("green" if all(t["status"] == "OK" for t in checks) else "red"),
        "version": APP_VERSION,
    }


def _snapshot():
    with state_lock:
        return (dict(state["mapping"]), dict(state["torques"]), dict(state["s3"])), state["db_ok"], state["updated_at"]


def _all_stations():
    data, db_ok, updated_at = _snapshot()
    stations = [build_station(n, *data) for n in range(1, TOTAL_STATIONS + 1)]
    return stations, db_ok, updated_at


def _summary(stations):
    """Home-page tiles: L3 (torque wrenches) and S3 controls, counted separately."""
    summary = []
    for st in stations:
        tools = [t for t in st["tools"] if not t["hidden"]]
        summary.append({"id": st["station"], "status": st["status"], "mat_number": st["mat_number"],
                        "l3_ok": sum(t["status"] == "OK" for t in tools), "l3_total": len(tools),
                        "l3_skipped": len(st["tools"]) - len(tools),   # Set Count 0 for this vehicle
                        "s3_ok": sum(c["status"] == "OK" for c in st["s3"]), "s3_total": len(st["s3"])})
    return summary


# ---------- manager login ----------

def current_user():
    return session.get("user")


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def csrf_ok():
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf") or ""
    return bool(sent) and bool(expected) and hmac.compare_digest(sent, expected)


def _safe_next(url):
    return url if url and url.startswith("/") and not url.startswith("//") else url_for("index")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    next_url = _safe_next(request.values.get("next"))
    if request.method == "POST":
        if not csrf_ok():
            abort(400)
        username = request.form.get("username", "").strip()
        password_hash = MANAGERS.get(username.lower())
        if password_hash and check_password_hash(password_hash, request.form.get("password", "")):
            session.clear()
            session["user"] = username
            logger.info(f"Manager login: {username}")
            return redirect(next_url)
        time.sleep(1)  # slow down password guessing
        error = "Wrong username or password."
    return render_template("login.html", error=error, next_url=next_url, db_ok=state["db_ok"])


@app.route("/logout", methods=["POST"])
def logout():
    if not csrf_ok():
        abort(400)
    session.clear()
    return redirect(_safe_next(request.form.get("next")))


# ---------- saving circle positions into the station template ----------

_TOOLS_BLOCK = re.compile(r"\{%-?\s*set\s+tools\s*=\s*\[.*?\]\s*-?%\}", re.DOTALL)


def save_positions(station_id, positions, username):
    """Write new x / y (percent) for the station's wrenches into templates/station_<n>.html.

    Only positions change; the wrench list and everything else in the file stay as they are.
    """
    name = station_template(station_id)
    if name == "station_generic.html":
        raise ValueError(f"Station {station_id} has no template of its own yet - create station_{station_id}.html first.")
    path = os.path.join(app.root_path, "templates", name)
    with open(path, encoding="utf-8") as f:
        source = f.read()
    if station_config(station_id)["error"]:
        raise ValueError("Fix the mistake in the station template first: " + station_config(station_id)["error"])
    if len(_TOOLS_BLOCK.findall(source)) != 1:
        raise ValueError(f"{name}: expected exactly one '{{% set tools = [...] %}}' block.")

    lines = []
    for t in station_config(station_id)["tools"]:
        x, y = t["x"], t["y"]
        p = positions.get(t["t_no"])
        if p is not None:
            x, y = (round(min(100.0, max(0.0, float(p[k]))), 1) for k in ("x", "y"))
            x, y = (int(v) if float(v).is_integer() else v for v in (x, y))
        entry = {"t_no": t["t_no"], "name": t["name"]}
        if x is not None:
            entry.update(x=x, y=y)
        lines.append("    " + json.dumps(entry, ensure_ascii=False) + ",")
    block = "{% set tools = [\n" + "\n".join(lines) + "\n] %}"

    shutil.copyfile(path, path + ".bak")
    new_source = _TOOLS_BLOCK.sub(lambda m: block, source)
    stamp = f"{{# positions last saved {datetime.now():%d-%m-%Y %H:%M} by {username} #}}"
    new_source = re.sub(r"\{# positions last saved .*? #\}\n?", "", new_source)
    new_source = new_source.replace(block, stamp + "\n" + block)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_source)
    os.replace(tmp, path)
    _template_cache.pop(path, None)


@app.route("/api/station/<int:station_id>/positions", methods=["POST"])
def api_save_positions(station_id):
    if not current_user():
        return jsonify({"error": "Please log in as a line manager."}), 401
    if not csrf_ok():
        return jsonify({"error": "Session expired - reload the page and try again."}), 403
    if not 1 <= station_id <= TOTAL_STATIONS:
        abort(404)
    body = request.get_json(silent=True) or {}
    try:
        positions = {str(k).upper(): {"x": float(v["x"]), "y": float(v["y"])}
                     for k, v in (body.get("positions") or {}).items()}
        save_positions(station_id, positions, current_user())
    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"error": str(e) or "Invalid positions."}), 400
    logger.info(f"Station {station_id} positions saved by {current_user()}")
    return jsonify({"ok": True})


@app.context_processor
def _globals():
    return {"line_title": LINE_TITLE, "demo_mode": DEMO_MODE, "app_version": APP_VERSION,
            "user": current_user(), "csrf_token": csrf_token()}


@app.route("/display-check")
def display_check():
    """Open this on a new screen (e.g. the digital standee) to see its browser and screen size,
    and to switch the page rotation for that screen."""
    return render_template("display_check.html", db_ok=state["db_ok"])


@app.route("/")
def index():
    stations, db_ok, updated_at = _all_stations()
    return render_template("index.html", stations=_summary(stations), db_ok=db_ok, updated_at=updated_at)


@app.route("/station/<int:station_id>")
def station(station_id):
    if not 1 <= station_id <= TOTAL_STATIONS:
        abort(404)
    data, db_ok, updated_at = _snapshot()
    st = build_station(station_id, *data)
    # a template with a mistake is shown with the plain layout and the error, instead of a crash
    return render_template("station_generic.html" if st["error"] else station_template(station_id),
                           station_id=station_id, st=st,
                           total_stations=TOTAL_STATIONS, db_ok=db_ok, updated_at=updated_at)


@app.route("/api/status")
def api_status():
    stations, db_ok, updated_at = _all_stations()
    return jsonify({"stations": _summary(stations), "db_ok": db_ok, "updated_at": updated_at,
                    "version": APP_VERSION})


@app.route("/api/station/<int:station_id>")
def api_station(station_id):
    if not 1 <= station_id <= TOTAL_STATIONS:
        abort(404)
    data, db_ok, updated_at = _snapshot()
    return jsonify({**build_station(station_id, *data), "db_ok": db_ok, "updated_at": updated_at})


def hash_password():
    """python app.py hash-password  ->  prints a line to paste under [MANAGERS] in config.ini"""
    username = input("Manager username: ").strip().lower()
    password = getpass.getpass("Password: ")
    if len(password) < 8 or password != getpass.getpass("Repeat password: "):
        print("Passwords must match and have at least 8 characters.")
        return
    print("\nAdd this line under [MANAGERS] in config.ini, then restart the app:\n")
    print(f"{username} = {generate_password_hash(password)}")


if __name__ == "__main__":
    if sys.argv[1:] == ["hash-password"]:
        hash_password()
        sys.exit(0)
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
