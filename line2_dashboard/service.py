"""Builds the dashboard view model from the two Line 2 tables."""
from datetime import datetime

from . import config, db
from .parser import to_record


def _station_status(records):
    if not records:
        return "WAITING"
    if any(r["status"] == "NOT OK" for r in records):
        return "NOT OK"
    if all(r["status"] == "OK" for r in records):
        return "OK"
    return "UNKNOWN"


def build_stations(rows, strict_station_match=True):
    """Group joined mapping/log rows into one entry per station.

    For each station only the latest record per tool tag (type_data) is kept,
    and only records logged at that station (unless strict matching is off).
    Rows must be ordered newest-first within each station.
    """
    stations = {}
    for row in rows:
        number = int(row["StationNumber"])
        station = stations.setdefault(number, {
            "station": number,
            "vc_number": str(row.get("VC_Number") or "").strip(),
            "mat_number": str(row.get("MAT_Number") or "").strip(),
            "records": [],
            "_seen_tags": set(),
        })
        if row.get("data") is None and row.get("type_data") is None:
            continue
        record = to_record(row)
        if strict_station_match and record["station"] not in (None, number):
            continue
        if record["tag"] in station["_seen_tags"]:
            continue
        station["_seen_tags"].add(record["tag"])
        station["records"].append(record)

    result = []
    for number in sorted(stations):
        station = stations[number]
        del station["_seen_tags"]
        records = station["records"]
        records.sort(key=lambda r: (_tag_sort_key(r["tag"])))
        station["status"] = _station_status(records)
        station["last_update"] = max((r["time"] for r in records if r["time"]), default=None)
        station["ok_count"] = sum(r["status"] == "OK" for r in records)
        station["not_ok_count"] = sum(r["status"] == "NOT OK" for r in records)
        station["bypass_count"] = sum(r["mode"] == "BYPASS" for r in records)
        result.append(station)
    return result


def _tag_sort_key(tag):
    digits = "".join(ch for ch in tag if ch.isdigit())
    return (int(digits) if digits else 10**9, tag)


def summarize(stations):
    return {
        "stations": len(stations),
        "ok": sum(s["status"] == "OK" for s in stations),
        "not_ok": sum(s["status"] == "NOT OK" for s in stations),
        "waiting": sum(s["status"] == "WAITING" for s in stations),
        "bypass": sum(s["bypass_count"] for s in stations),
    }


def line_snapshot():
    stations = build_stations(db.fetch_station_rows(), config.STRICT_STATION_MATCH)
    return {
        "line_name": config.LINE_NAME,
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "demo": config.DEMO_MODE,
        "summary": summarize(stations),
        "stations": stations,
    }


def recent_events(limit=None):
    rows = db.fetch_recent_events(limit or config.EVENTS_LIMIT)
    return [to_record(row) for row in rows]
