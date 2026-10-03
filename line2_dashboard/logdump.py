"""
Legacy source (source = logdump): the smartapp log table.

  dbo.Station_Mapping                  vehicle at each station
  dbo.smartapp_linedata_line_log_dump  one JSON row per tool event, e.g.
    {"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781",
     "Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}
"+2" is not valid JSON (SQL Server's JSON_VALUE rejects it), so it is parsed here in Python.
"""
import json
import re

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



def fetch_station_rows(conn, shop_id=None):
    """Every station's current vehicle joined to that vehicle's log rows, newest first.

    `=` on varchar ignores trailing spaces in SQL Server, so padded mat_no values still match.
    Stations with no log rows yet come back once with NULL log columns.
    """
    shop_filter = " AND l.shop_id_id = ?" if shop_id else ""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT m.StationNumber, m.VC_Number, m.MAT_Number,
               l.in_date_time, l.type_data, l.data
        FROM dbo.Station_Mapping AS m
        LEFT JOIN dbo.smartapp_linedata_line_log_dump AS l
               ON l.mat_no = m.MAT_Number{shop_filter}
        ORDER BY m.StationNumber, l.in_date_time DESC, l.id DESC
    """, *([shop_id] if shop_id else []))
    columns = [c[0] for c in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]
