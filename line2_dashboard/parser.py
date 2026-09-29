"""Parsing of the JSON-ish `data` column in smartapp_linedata_line_log_dump.

The PLC writes values such as  "Set Count":+2  which is not valid JSON (and makes
SQL Server's ISJSON/JSON_VALUE reject the row), so parsing is done here leniently.
"""
import json
import re

_LEADING_PLUS = re.compile(r'(:\s*)\+(?=\d)')
_PAIR = re.compile(r'"([^"]+)"\s*:\s*(?:"([^"]*)"|([+-]?\d+(?:\.\d+)?))')
_STATION_NO = re.compile(r"(\d+)")
_NAME_PREFIX = re.compile(r"^\s*ST\s*0*(\d+)\b", re.IGNORECASE)
_TORQUE = re.compile(r"(\d+(?:\.\d+)?)\s*Nm", re.IGNORECASE)


def parse_payload(raw):
    """Return the payload as a dict; never raises."""
    if not raw:
        return {}
    text = raw.strip()
    for candidate in (text, _LEADING_PLUS.sub(r"\1", text)):
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else {}
        except ValueError:
            pass
    # Last resort: pull out "key": value pairs individually.
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
    match = _STATION_NO.search(str(payload.get("Station No", "")))
    if match:
        return int(match.group(1))
    match = _NAME_PREFIX.match(str(payload.get("Name", "")))
    return int(match.group(1)) if match else None


def normalize_status(value):
    status = str(value or "").strip().upper().replace("_", " ")
    if status in ("OK", "NOT OK"):
        return status
    if status in ("NOK", "NG", "NOTOK"):
        return "NOT OK"
    return status or "UNKNOWN"


def to_record(row):
    """Turn a log row (dict with id, in_date_time, mat_no, type_data, data) into a display record."""
    payload = parse_payload(row.get("data"))
    name = str(payload.get("Name", "")).strip()
    torque = _TORQUE.search(name)
    when = row.get("in_date_time")
    return {
        "id": row.get("id"),
        "time": when.isoformat(sep=" ", timespec="seconds") if hasattr(when, "isoformat") else when,
        "mat": str(payload.get("MAT") or row.get("mat_no") or "").strip(),
        "tag": str(row.get("type_data") or "").strip(),
        "name": name,
        "torque_nm": _to_number(torque.group(1)) if torque else None,
        "station": station_of(payload),
        "operator": str(payload.get("Operator", "")).strip(),
        "mode": str(payload.get("Mode", "")).strip().upper(),
        "set_count": _to_number(payload.get("Set Count")),
        "actual_count": _to_number(payload.get("Actual Count")),
        "status": normalize_status(payload.get("Status")),
    }
