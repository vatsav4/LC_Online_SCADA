"""
Line-2 torque dashboard.

Two tables on the Line-2 SQL Server (reachable only on port 49561):
  dbo.Station_Mapping      StationNumber, VC_Number, MAT_Number   (vehicle at each station)
  dbo.Torques_Actual_Data  T_No, T_Name, Set_Counts, Actual_Counts, Active_Bypass
                           (one row per wrench, written by wincc/Torques_To_SQL_Action.vbs)

Which wrenches a station shows, and where each circle sits on the chassis
picture, is written in that station's template: templates/station_<n>.html
    {% set tools = [ {"t_no": "T18", "name": "ARB bolt fitment", "x": 16, "y": 33}, ... ] %}
The app reads that list from the template itself, so the station page and its
tile on the overview always agree. Open /station/<n>?setup=1 to drag the
circles and copy the x / y numbers into the template.

A background thread reads both tables every few seconds and keeps the latest
values in memory; pages and JSON endpoints only read that snapshot.
"""

import configparser
import logging
import os
import threading
import time
from datetime import datetime

from flask import Flask, abort, jsonify, render_template
from jinja2 import nodes

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
TOTAL_STATIONS = int(_get("MAIN", "total_stations", "17"))
DEMO_MODE = _get("MAIN", "demo_mode", "false").strip().lower() in ("1", "true", "yes", "on")

# ================= LOGGING =================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LINE2_DASHBOARD")

# ================= SHARED STATE =================
# Written only by poll_loop(), read only by routes/API handlers.

state_lock = threading.Lock()
state = {
    "mapping": {},   # {station_no: {"vc": .., "mat": ..}}
    "torques": {},   # {"T1": {"name": .., "set": .., "actual": .., "bypass": bool}}
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
    return mapping, torques


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
               "T40": ("Air tank bracket", 4, 10, 1)}
    return ({n: {"vc": vc, "mat": mat} for n, (vc, mat) in mapping.items()},
            {t: {"name": n, "set": s, "actual": a, "bypass": bool(b)} for t, (n, s, a, b) in torques.items()})


def poll_once():
    try:
        if DEMO_MODE:
            mapping, torques = demo_tables()
        else:
            conn = connect(LINE_DB)
            try:
                mapping, torques = fetch_tables(conn)
            finally:
                conn.close()
        with state_lock:
            state["mapping"], state["torques"] = mapping, torques
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
app.config["TEMPLATES_AUTO_RELOAD"] = True  # edited station templates show up on refresh


# ---------- station templates ----------

def station_template(station_id):
    name = f"station_{station_id}.html"
    if os.path.exists(os.path.join(app.root_path, "templates", name)):
        return name
    return "station_generic.html"


_template_cache = {}  # template file -> (mtime, config)


def station_config(station_id):
    """The `chassis_image` and `tools` set at the top of templates/station_<n>.html.

    Re-read automatically when the template file changes, so editing T_Nos
    needs no restart (only a browser refresh).
    """
    name = station_template(station_id)
    path = os.path.join(app.root_path, "templates", name)
    mtime = os.path.getmtime(path)
    cached = _template_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]

    found = {}
    with open(path, encoding="utf-8") as f:
        tree = app.jinja_env.parse(f.read())
    for node in tree.find_all(nodes.Assign):
        if isinstance(node.target, nodes.Name) and node.target.name in ("tools", "chassis_image"):
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
        tools.append({"t_no": str(t["t_no"]).strip().upper(), "name": str(t.get("name") or "").strip(),
                      "x": min(100, max(0, x)) if placed else None,
                      "y": min(100, max(0, y)) if placed else None})
    config = {"chassis_image": found.get("chassis_image") or "chassis-top.svg", "tools": tools}
    _template_cache[path] = (mtime, config)
    return config


def build_station(station_id, mapping, torques):
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
            "tag": t["t_no"],
            "label": t["name"] or (row or {}).get("name") or t["t_no"],
            "x": t["x"], "y": t["y"],
            "set": (row or {}).get("set"),
            "actual": (row or {}).get("actual"),
            "mode": "BYPASS" if (row or {}).get("bypass") else ("ACTIVE" if row else ""),
            "status": status,
        })
    return {
        "station": station_id,
        "vc_number": vehicle.get("vc", ""),
        "mat_number": vehicle.get("mat", ""),
        "image": config["chassis_image"],
        "tools": tools,
        "status": "idle" if not tools else ("green" if all(t["status"] == "OK" for t in tools) else "red"),
    }


def _snapshot():
    with state_lock:
        return dict(state["mapping"]), dict(state["torques"]), state["db_ok"], state["updated_at"]


def _all_stations():
    mapping, torques, db_ok, updated_at = _snapshot()
    stations = [build_station(n, mapping, torques) for n in range(1, TOTAL_STATIONS + 1)]
    return stations, db_ok, updated_at


def _summary(stations):
    return [{"id": st["station"], "status": st["status"], "mat_number": st["mat_number"],
             "ok": sum(t["status"] == "OK" for t in st["tools"]), "total": len(st["tools"])}
            for st in stations]


@app.context_processor
def _globals():
    return {"line_title": LINE_TITLE, "demo_mode": DEMO_MODE}


@app.route("/")
def index():
    stations, db_ok, updated_at = _all_stations()
    return render_template("index.html", stations=_summary(stations), db_ok=db_ok, updated_at=updated_at)


@app.route("/station/<int:station_id>")
def station(station_id):
    if not 1 <= station_id <= TOTAL_STATIONS:
        abort(404)
    mapping, torques, db_ok, updated_at = _snapshot()
    return render_template(station_template(station_id), station_id=station_id,
                           st=build_station(station_id, mapping, torques),
                           total_stations=TOTAL_STATIONS, db_ok=db_ok, updated_at=updated_at)


@app.route("/api/status")
def api_status():
    stations, db_ok, updated_at = _all_stations()
    return jsonify({"stations": _summary(stations), "db_ok": db_ok, "updated_at": updated_at})


@app.route("/api/station/<int:station_id>")
def api_station(station_id):
    if not 1 <= station_id <= TOTAL_STATIONS:
        abort(404)
    mapping, torques, db_ok, updated_at = _snapshot()
    return jsonify({**build_station(station_id, mapping, torques), "db_ok": db_ok, "updated_at": updated_at})


if __name__ == "__main__":
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
