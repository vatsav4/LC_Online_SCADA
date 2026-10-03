import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "line2_dashboard"))

import app as line2  # noqa: E402
from wincc_source import build_stations_from_status, fetch  # noqa: E402


def _row(station, tool, set_count, actual, status, mat="MAT1", vc="VC1", minute=0, mode="ACTIVE", name=None):
    return {"StationNumber": station, "Tool": tool, "ToolName": name, "TorqueNm": None,
            "SetCount": set_count, "ActualCount": actual, "Status": status, "Mode": mode,
            "MAT_Number": mat, "VC_Number": vc, "UpdatedAt": datetime(2026, 10, 3, 10, minute)}


def test_status_rows_become_stations():
    rows = [_row(1, "T1", 5, 5, "OK", name="SG Tightening"),
            _row(1, "T2", 5, 0, "NOT OK", mode="BYPASS"),
            _row(1, "T10", 5, 5, None)]                    # no OK tag -> judged from counts
    st = build_stations_from_status(rows)[1]
    assert (st["mat_number"], st["vc_number"], st["status"]) == ("MAT1", "VC1", "red")
    assert [t["tag"] for t in st["tools"]] == ["T1", "T2", "T10"]
    assert st["tools"][0]["label"] == "SG Tightening"
    assert (st["tools"][1]["status"], st["tools"][1]["mode"]) == ("NOT OK", "BYPASS")
    assert st["tools"][2]["status"] == "OK"


def test_new_vehicle_does_not_inherit_old_green_boxes():
    rows = [_row(1, "T1", 5, 5, "OK", mat="MAT_OLD", minute=1),
            _row(1, "T2", 5, 1, "NOT OK", mat="MAT_NEW", minute=2)]
    st = build_stations_from_status(rows)[1]
    assert st["mat_number"] == "MAT_NEW"
    assert (st["tools"][0]["status"], st["tools"][0]["actual"]) == ("PENDING", None)
    assert st["status"] == "red"


def test_station_mapping_fills_missing_vc_mat_and_empty_stations():
    rows = [_row(1, "T1", 5, 5, "OK", mat=None, vc=None)]
    mapping = {1: {"vc_number": "55072654300R", "mat_number": "MAT784062TFJ12788"},
               2: {"vc_number": "V2", "mat_number": "M2"}}
    stations = build_stations_from_status(rows, mapping)
    assert stations[1]["mat_number"] == "MAT784062TFJ12788" and stations[1]["status"] == "green"
    assert stations[2]["status"] == "idle"


class _Cursor:
    def __init__(self, results):
        self.results, self.description = results, None

    def execute(self, sql):
        self.current = self.results.pop(0)
        self.description = [(c,) for c in self.current["cols"]]

    def fetchall(self):
        return self.current["rows"]

    def fetchone(self):
        return self.current["rows"][0] if self.current["rows"] else None


class _Conn:
    def __init__(self, results):
        self.c = _Cursor(results)

    def cursor(self):
        return self.c

    def close(self):
        pass


def _fake_db(heartbeat_age):
    cols = ["StationNumber", "Tool", "ToolName", "TorqueNm", "SetCount", "ActualCount",
            "Status", "Mode", "MAT_Number", "VC_Number", "UpdatedAt"]
    return _Conn([
        {"cols": cols, "rows": [(1, "T1", "SG Tightening", None, 5, 5, "OK", "ACTIVE", "MAT1", "VC1",
                                 datetime(2026, 10, 3, 10))]},
        {"cols": ["age"], "rows": [(heartbeat_age,)] if heartbeat_age is not None else []},
        {"cols": ["StationNumber", "VC_Number", "MAT_Number"], "rows": [(1, "VC1", "MAT1"), (2, "VC2", "MAT2")]},
    ])


def test_fetch_reads_status_heartbeat_and_mapping():
    rows, age, mapping = fetch(_fake_db(12), True)
    assert rows[0]["Tool"] == "T1" and age == 12 and set(mapping) == {1, 2}


def test_app_wincc_source_online_and_offline(monkeypatch):
    monkeypatch.setattr(line2, "SOURCE", "wincc")
    monkeypatch.setattr(line2, "connect", lambda cfg: _fake_db(20))
    line2.poll_once()
    client = line2.app.test_client()
    status = client.get("/api/status").get_json()
    assert status["db_ok"] is True and [s["status"] for s in status["stations"]] == ["green", "idle"]
    assert "T1: SG Tightening" in client.get("/station/1").get_data(as_text=True)

    monkeypatch.setattr(line2, "connect", lambda cfg: _fake_db(500))   # WinCC script stopped
    line2.poll_once()
    assert client.get("/api/status").get_json()["db_ok"] is False

    monkeypatch.setattr(line2, "connect", lambda cfg: _fake_db(None))  # never ran
    line2.poll_once()
    assert client.get("/api/status").get_json()["db_ok"] is False
