"""
Line-2 torque dashboard.

Interchangeable data sources, chosen with [MAIN] source in config.ini:
  source = sql    -> the SQL tables below (default)
  source = opcua  -> live SCADA tags over OPC UA, see opcua_source.py / tag_map.csv
Both produce the same station/tool snapshot, so the pages are identical.

SQL source - one SQL Server (only reachable on a non-default port, e.g. 49561):
  SQL_LINE -> Industry4_157.dbo.Station_Mapping
                (StationNumber, VC_Number, MAT_Number - vehicle at each station)
           -> Industry4_157.dbo.smartapp_linedata_line_log_dump
                (mat_no, type_data = tool tag, data = JSON payload per tool)

A background thread polls both tables on an interval and keeps the latest
snapshot in memory. Pages and JSON endpoints read from that snapshot only -
no per-request SQL round trips.

The `data` column looks like:
  {"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781",
   "Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}
"+2" is not valid JSON (SQL Server's JSON_VALUE rejects it), so it is parsed here in Python.

Which tools a station has is taken from the log for the vehicle currently at
that station. STATION_TOOLS below can optionally pin the expected tags per
station so a tool shows up (red, "awaiting data") before its first tightening.
"""

import os
import re
import json
import time
import logging
import configparser
import threading
from datetime import datetime

from flask import Flask, jsonify, render_template, abort

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
CHASSIS_IMAGE = _get("MAIN", "chassis_image", "chassis.svg")  # file in static/
DEMO_MODE = _get("MAIN", "demo_mode", "false").strip().lower() in ("1", "true", "yes", "on")
SOURCE = _get("MAIN", "source", "sql").strip().lower()  # "sql" or "opcua"


OPCUA = {
    "endpoint": _get("OPCUA", "endpoint", "opc.tcp://127.0.0.1:4840"),
    "username": _get("OPCUA", "username", "").strip() or None,
    "password": _get("OPCUA", "password", ""),
    # e.g. "Basic256Sha256,SignAndEncrypt,client_cert.der,client_key.pem"; empty = no security
    "security": _get("OPCUA", "security", "").strip() or None,
    "publishing_interval_ms": int(_get("OPCUA", "publishing_interval_ms", "1000")),
    "retry_seconds": int(_get("OPCUA", "retry_seconds", "10")),
    "tag_map": os.path.join(os.path.dirname(__file__), _get("OPCUA", "tag_map", "tag_map.csv")),
    "ok_values": [v.strip() for v in _get("OPCUA", "ok_values", "1,true,ok").split(",")],
    "bypass_values": [v.strip() for v in _get("OPCUA", "bypass_values", "1,true,bypass").split(",")],
    # Take VC/MAT from SQL Station_Mapping for stations whose VC/MAT are not in tag_map.csv.
    "mat_from_sql": _get("OPCUA", "mat_from_sql", "false").strip().lower() in ("1", "true", "yes", "on"),
}

# Optional: only read log rows for this shop_id_id (if the log table is shared between lines).
SHOP_ID = _get("FILTER", "shop_id", "").strip() or None

# Optional: tool tags each station is expected to have. Stations not listed
# just show whatever tools were logged for their current vehicle.
STATION_TOOLS = {
    # 5: ["T18", "T23"],
    # 8: ["T19", "T37"],
}

# ================= LOGGING =================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LINE2_DASHBOARD")

# ================= SHARED STATE =================
# Written only by poll_loop(), read only by routes/API handlers.

state_lock = threading.Lock()
state = {
    "stations": {},  # {station_no: {station, vc_number, mat_number, status, tools: [...]}}
    "updated_at": None,
    "db_ok": False,
}


# ================= PAYLOAD PARSING =================

_LEADING_PLUS = re.compile(r'(:\s*)\+(?=\d)')
_PAIR = re.compile(r'"([^"]+)"\s*:\s*(?:"([^"]*)"|([+-]?\d+(?:\.\d+)?))')
_DIGITS = re.compile(r"(\d+)")
_NAME_STATION = re.compile(r"^\s*ST\s*0*(\d+)\b", re.IGNORECASE)
_TORQUE = re.compile(r"(\d+(?:\.\d+)?)\s*Nm\b", re.IGNORECASE)


def parse_payload(raw):
    """Return the `data` JSON as a dict; tolerant of +N numbers and minor breakage. Never raises."""
    if not raw:
        return {}
    text = str(raw).strip()
    for candidate in (text, _LEADING_PLUS.sub(r"\1", text)):
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else {}
        except ValueError:
            pass
    result = {}
    for key, str_val, num_val in _PAIR.findall(text):
        result[key] = str_val if num_val == "" else _to_number(num_val)
    return result


def _to_number(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        num = float(str(value).strip())
    except ValueError:
        return None
    return int(num) if num.is_integer() else num


def station_of(payload):
    """Station number from "Station No" ("STATION 8"), else from the Name prefix ("ST08 ...")."""
    match = _DIGITS.search(str(payload.get("Station No", "")))
    if match:
        return int(match.group(1))
    match = _NAME_STATION.match(str(payload.get("Name", "")))
    return int(match.group(1)) if match else None


def tool_label(name, tag):
    """"ST08 50Nm T37 Steering pressure line" -> "Steering pressure line" (station, torque and tag removed)."""
    label = _NAME_STATION.sub("", name or "")
    label = _TORQUE.sub("", label)
    if tag:
        label = re.sub(rf"\b{re.escape(tag)}\b", "", label, flags=re.IGNORECASE)
    return " ".join(label.split()) or tag


def tool_from_row(row):
    """Log row (dict with type_data, data, in_date_time) -> tool dict for the UI."""
    payload = parse_payload(row.get("data"))
    tag = str(row.get("type_data") or "").strip()
    name = str(payload.get("Name", "")).strip()
    torque = _TORQUE.search(name)
    set_count = _to_number(payload.get("Set Count"))
    actual_count = _to_number(payload.get("Actual Count"))
    status = str(payload.get("Status", "")).strip().upper()
    if status not in ("OK", "NOT OK"):
        # No usable Status from the PLC: same rule as the Line-3 andon (actual < set -> red).
        status = "NOT OK" if set_count is not None and (actual_count or 0) < set_count else "OK"
    when = row.get("in_date_time")
    return {
        "tag": tag,
        "label": tool_label(name, tag),
        "torque_nm": _to_number(torque.group(1)) if torque else None,
        "station": station_of(payload),
        "mode": str(payload.get("Mode", "")).strip().upper(),
        "set": set_count,
        "actual": actual_count,
        "status": status,
        "updated": when.strftime("%d-%m-%Y %H:%M:%S") if hasattr(when, "strftime") else when,
    }


def _tag_key(tag):
    digits = _DIGITS.search(tag or "")
    return (int(digits.group(1)) if digits else 10**9, tag)


def _pending_tool(tag):
    return {"tag": tag, "label": "Awaiting data", "torque_nm": None, "station": None, "mode": "",
            "set": None, "actual": None, "status": "PENDING", "updated": None}


def build_stations(rows, station_tools=None):
    """Group mapping+log rows (newest log first per station) into one entry per station.

    Keeps only log rows recorded AT that station for its current vehicle, and only
    the newest row per tool tag.
    """
    station_tools = station_tools or {}
    stations = {}
    for row in rows:
        number = int(row["StationNumber"])
        st = stations.setdefault(number, {
            "station": number,
            "vc_number": str(row.get("VC_Number") or "").strip(),
            "mat_number": str(row.get("MAT_Number") or "").strip(),
            "tools": {},
        })
        if row.get("type_data") is None:
            continue
        tool = tool_from_row(row)
        if tool["station"] not in (None, number) or tool["tag"] in st["tools"]:
            continue
        st["tools"][tool["tag"]] = tool

    for number, st in stations.items():
        tools = st["tools"]
        for tag in station_tools.get(number, []):
            tools.setdefault(tag, _pending_tool(tag))
        st["tools"] = sorted(tools.values(), key=lambda t: _tag_key(t["tag"]))
        st["status"] = station_status(st["tools"])
    return stations


def station_status(tools):
    if not tools:
        return "idle"
    return "green" if all(t["status"] == "OK" for t in tools) else "red"


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


def fetch_station_rows(conn):
    """Every station's current vehicle joined to that vehicle's log rows, newest first.

    `=` on varchar ignores trailing spaces in SQL Server, so padded mat_no values still match.
    Stations with no log rows yet come back once with NULL log columns.
    """
    shop_filter = " AND l.shop_id_id = ?" if SHOP_ID else ""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT m.StationNumber, m.VC_Number, m.MAT_Number,
               l.in_date_time, l.type_data, l.data
        FROM dbo.Station_Mapping AS m
        LEFT JOIN dbo.smartapp_linedata_line_log_dump AS l
               ON l.mat_no = m.MAT_Number{shop_filter}
        ORDER BY m.StationNumber, l.in_date_time DESC, l.id DESC
    """, *([SHOP_ID] if SHOP_ID else []))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def load_rows():
    if DEMO_MODE:
        import demo_data

        return demo_data.station_rows()
    conn = connect(LINE_DB)
    try:
        return fetch_station_rows(conn)
    finally:
        conn.close()


def fetch_mapping():
    """Station -> VC/MAT from Station_Mapping (14 rows; used only by the OPC UA source)."""
    conn = connect(LINE_DB)
    try:
        cur = conn.cursor()
        cur.execute("SELECT StationNumber, VC_Number, MAT_Number FROM dbo.Station_Mapping")
        return {int(r[0]): {"vc_number": str(r[1] or "").strip(), "mat_number": str(r[2] or "").strip()}
                for r in cur.fetchall()}
    finally:
        conn.close()


opcua_source = None  # OpcUaSource instance when SOURCE == "opcua"
opcua_tag_map = []


def start_opcua():
    global opcua_source, opcua_tag_map
    from opcua_source import OpcUaSource, load_tag_map

    opcua_tag_map = load_tag_map(OPCUA["tag_map"])
    opcua_source = OpcUaSource(
        OPCUA["endpoint"], [r["node_id"] for r in opcua_tag_map],
        username=OPCUA["username"], password=OPCUA["password"], security=OPCUA["security"],
        publishing_interval_ms=OPCUA["publishing_interval_ms"], retry_seconds=OPCUA["retry_seconds"],
    ).start()


def load_stations():
    """Latest stations from whichever source is configured. Returns (stations, source_ok)."""
    if SOURCE == "opcua":
        from opcua_source import build_stations_from_tags

        values, updated, connected = opcua_source.snapshot()
        mapping = fetch_mapping() if OPCUA["mat_from_sql"] else None
        stations = build_stations_from_tags(opcua_tag_map, values, updated, mapping,
                                            OPCUA["ok_values"], OPCUA["bypass_values"])
        return stations, connected
    return build_stations(load_rows(), STATION_TOOLS), True


def poll_once():
    try:
        stations, source_ok = load_stations()
        with state_lock:
            state["stations"] = stations
            state["updated_at"] = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            state["db_ok"] = source_ok
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


@app.context_processor
def _globals():
    return {"line_title": LINE_TITLE, "chassis_image": CHASSIS_IMAGE, "demo_mode": DEMO_MODE}


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


@app.route("/api/status")
def api_status():
    stations, db_ok, updated_at = _snapshot()
    return jsonify({"stations": _summary(stations), "db_ok": db_ok, "updated_at": updated_at})


@app.route("/api/station/<int:station_id>")
def api_station(station_id):
    stations, db_ok, updated_at = _snapshot()
    if station_id not in stations:
        abort(404)
    return jsonify({**stations[station_id], "db_ok": db_ok, "updated_at": updated_at})


if __name__ == "__main__":
    if SOURCE == "opcua":
        start_opcua()
    threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=WEB_PORT, threaded=True)
