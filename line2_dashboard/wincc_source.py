"""
Read the Line-2 status that the WinCC VBScript (wincc/Line2_SyncToolStatus.vbs)
writes into SQL. Used when config.ini has [MAIN] source = wincc.

Tables (created by wincc/line2_status.sql):
  dbo.Line2_Tool_Status       one row per station + tool, latest values
  dbo.Line2_Writer_Heartbeat  touched by WinCC every ~30 s while the script runs
"""
from datetime import datetime


def fetch(conn, with_mapping):
    """Return (status_rows, heartbeat_age_seconds or None, mapping or None) in one connection."""
    cur = conn.cursor()
    cur.execute("""
        SELECT StationNumber, Tool, ToolName, TorqueNm, SetCount, ActualCount,
               Status, Mode, MAT_Number, VC_Number, UpdatedAt
        FROM dbo.Line2_Tool_Status
    """)
    columns = [c[0] for c in cur.description]
    rows = [dict(zip(columns, r)) for r in cur.fetchall()]

    cur.execute("SELECT DATEDIFF(SECOND, LastSeen, SYSDATETIME()) FROM dbo.Line2_Writer_Heartbeat WHERE Id = 1")
    hb = cur.fetchone()
    heartbeat_age = int(hb[0]) if hb and hb[0] is not None else None

    mapping = None
    if with_mapping:
        cur.execute("SELECT StationNumber, VC_Number, MAT_Number FROM dbo.Station_Mapping")
        mapping = {int(r[0]): {"vc_number": str(r[1] or "").strip(), "mat_number": str(r[2] or "").strip()}
                   for r in cur.fetchall()}
    return rows, heartbeat_age, mapping


def _num(value):
    if value is None:
        return None
    num = float(value)
    return int(num) if num.is_integer() else num


def _text(value):
    return str(value or "").strip()


def _tag_key(tag):
    digits = "".join(ch for ch in tag if ch.isdigit())
    return (int(digits) if digits else 10**9, tag)


def _when(value):
    return value.strftime("%d-%m-%Y %H:%M:%S") if isinstance(value, datetime) else value


def build_stations_from_status(rows, mapping=None):
    """Status-table rows (+ optional Station_Mapping) -> the station dicts the pages use.

    Current vehicle per station: the MAT/VC written most recently by WinCC; if WinCC
    has no MAT tag for that station, Station_Mapping's. A tool row written for a
    DIFFERENT vehicle than the current one is shown as "awaiting data" (red), so a
    new vehicle never inherits the previous vehicle's green boxes.
    """
    mapping = mapping or {}
    by_station = {}
    for row in rows:
        by_station.setdefault(int(row["StationNumber"]), []).append(row)

    result = {}
    for number in sorted(set(by_station) | set(mapping)):
        st_rows = by_station.get(number, [])
        newest_first = sorted(st_rows, key=lambda r: r["UpdatedAt"] or datetime.min, reverse=True)
        mat = next((_text(r["MAT_Number"]) for r in newest_first if _text(r["MAT_Number"])), "")
        vc = next((_text(r["VC_Number"]) for r in newest_first if _text(r["VC_Number"])), "")
        mapped = mapping.get(number, {})
        mat = mat or mapped.get("mat_number", "")
        vc = vc or mapped.get("vc_number", "")

        tools = []
        for r in st_rows:
            row_mat = _text(r["MAT_Number"])
            stale = bool(mat and row_mat and row_mat != mat)
            set_count, actual = _num(r["SetCount"]), _num(r["ActualCount"])
            status = _text(r["Status"]).upper()
            if stale:
                status, actual = "PENDING", None
            elif status not in ("OK", "NOT OK"):
                if set_count is None or actual is None:
                    status = "PENDING"
                else:
                    status = "OK" if actual >= set_count else "NOT OK"
            tools.append({
                "tag": _text(r["Tool"]),
                "label": _text(r["ToolName"]) or _text(r["Tool"]),
                "torque_nm": _num(r["TorqueNm"]),
                "station": number,
                "mode": _text(r["Mode"]).upper() if not stale else "",
                "set": set_count,
                "actual": actual,
                "status": status,
                "updated": _when(r["UpdatedAt"]),
            })
        tools.sort(key=lambda t: _tag_key(t["tag"]))
        result[number] = {
            "station": number,
            "vc_number": vc,
            "mat_number": mat,
            "tools": tools,
            "status": "idle" if not tools else ("green" if all(t["status"] == "OK" for t in tools) else "red"),
        }
    return result
