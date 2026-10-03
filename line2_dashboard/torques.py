"""
Default source (source = torques): what the WinCC script wincc/Torques_To_SQL_Action.vbs logs.

  dbo.Station_Mapping      StationNumber, VC_Number, MAT_Number  - vehicle at each station
  dbo.Torques_Actual_Data  T_No, T_Name, Set_Counts, Actual_Counts, Active_Bypass - one row per wrench

The table has no station column, so which wrenches belong to which station comes
from the station layouts (layouts.py), which line managers edit on the station page.
"""


def fetch(conn):
    """Return (mapping_rows, torque_rows) as lists of dicts, in one connection."""
    cur = conn.cursor()
    cur.execute("SELECT StationNumber, VC_Number, MAT_Number FROM dbo.Station_Mapping")
    mapping = [{"StationNumber": r[0], "VC_Number": r[1], "MAT_Number": r[2]} for r in cur.fetchall()]
    cur.execute("SELECT T_No, T_Name, Set_Counts, Actual_Counts, Active_Bypass FROM dbo.Torques_Actual_Data")
    torques = [{"T_No": r[0], "T_Name": r[1], "Set_Counts": r[2], "Actual_Counts": r[3], "Active_Bypass": r[4]}
               for r in cur.fetchall()]
    return mapping, torques


def _num(value):
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def _text(value):
    return str(value or "").strip()


def tool_from_row(t_no, row):
    """One Torques_Actual_Data row (or None if the wrench has no row yet) -> tool dict for the UI."""
    if row is None:
        return {"tag": t_no, "label": "", "torque_nm": None, "mode": "", "set": None, "actual": None,
                "status": "PENDING", "updated": None}
    set_count, actual = _num(row["Set_Counts"]), _num(row["Actual_Counts"])
    if set_count is None or actual is None:
        status = "PENDING"
    else:
        status = "OK" if actual >= set_count else "NOT OK"
    return {
        "tag": t_no,
        "label": _text(row["T_Name"]),
        "torque_nm": None,
        "mode": "BYPASS" if row.get("Active_Bypass") in (True, 1, "1") else "ACTIVE",
        "set": set_count,
        "actual": actual,
        "status": status,
        "updated": None,
    }


def build_stations(mapping_rows, torque_rows, layouts):
    """Stations from Station_Mapping; each station's wrenches are the ones its layout lists."""
    by_tno = {_text(r["T_No"]).upper(): r for r in torque_rows}
    stations = {}
    numbers = {int(r["StationNumber"]) for r in mapping_rows} | set(layouts)
    mapped = {int(r["StationNumber"]): r for r in mapping_rows}
    for number in sorted(numbers):
        m = mapped.get(number, {})
        tools = [tool_from_row(t["t_no"], by_tno.get(t["t_no"].upper()))
                 for t in layouts.get(number, {}).get("tools", [])]
        stations[number] = {
            "station": number,
            "vc_number": _text(m.get("VC_Number")),
            "mat_number": _text(m.get("MAT_Number")),
            "tools": tools,
        }
    return stations


def all_tool_numbers(torque_rows):
    """Every T_No the WinCC script has logged, for the layout editor's picker."""
    return sorted({_text(r["T_No"]) for r in torque_rows if _text(r["T_No"])},
                  key=lambda t: (int("".join(c for c in t if c.isdigit()) or 10**9), t))
