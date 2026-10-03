import os
import sys
import time
import types

import pytest

import app as line2

TEMPLATES = os.path.join(os.path.dirname(line2.__file__), "templates")


def test_every_station_template_has_a_valid_tool_list():
    for n in range(1, line2.TOTAL_STATIONS + 1):
        cfg = line2.station_config(n)
        assert os.path.isfile(os.path.join(TEMPLATES, "..", "static", "chassis", cfg["chassis_image"])), n
        for t in cfg["tools"]:
            assert t["t_no"].startswith("T") and 0 <= t["x"] <= 100 and 0 <= t["y"] <= 100


def test_station_5_template_lists_its_wrenches():
    tools = line2.station_config(5)["tools"]
    assert [(t["t_no"], t["x"], t["y"]) for t in tools] == [("T18", 16, 33), ("T23", 78, 67)]


def test_template_edits_are_picked_up_without_restart(tmp_path, monkeypatch):
    (tmp_path / "templates").mkdir()
    page = tmp_path / "templates" / "station_99.html"
    page.write_text('{% extends "station_base.html" %}{% set tools = [{"t_no": "t7", "name": "A", "x": 150, "y": 10}] %}')
    monkeypatch.setattr(line2.app, "root_path", str(tmp_path))
    assert line2.station_config(99)["tools"] == [{"t_no": "T7", "name": "A", "x": 100, "y": 10}]
    page.write_text('{% extends "station_base.html" %}{% set tools = [{"t_no": "T8"}, {"name": "no t_no"}] %}')
    os.utime(page, (time.time() + 5, time.time() + 5))
    assert line2.station_config(99)["tools"] == [{"t_no": "T8", "name": "", "x": None, "y": None}]


def test_build_station_statuses():
    mapping = {5: {"vc": "VC5", "mat": "MAT5"}}
    torques = {"T18": {"name": "ARB", "set": 4, "actual": 4, "bypass": True},
               "T23": {"name": "ARB 2", "set": 4, "actual": 1, "bypass": False}}
    st = line2.build_station(5, mapping, torques)
    assert (st["vc_number"], st["mat_number"], st["status"]) == ("VC5", "MAT5", "red")
    t18, t23 = st["tools"]
    assert (t18["status"], t18["mode"], t18["label"]) == ("OK", "BYPASS", "ARB bolt fitment")
    assert t23["status"] == "NOT OK"
    assert line2.build_station(5, mapping, {})["tools"][0]["status"] == "PENDING"
    assert line2.build_station(3, mapping, torques)["status"] == "idle"   # no wrenches in template


def test_fetch_tables_reads_both_tables():
    class Cur:
        def __init__(self):
            self.results = [[(1, "VC1 ", "MAT1")], [("t1 ", " SG ", 5, 3, 1), (None, "", 0, 0, 0)]]
        def execute(self, sql):
            self.rows = self.results.pop(0)
        def fetchall(self):
            return self.rows
    conn = types.SimpleNamespace(cursor=lambda: Cur())
    mapping, torques = line2.fetch_tables(conn)
    assert mapping == {1: {"vc": "VC1", "mat": "MAT1"}}
    assert torques == {"T1": {"name": "SG", "set": 5, "actual": 3, "bypass": True}}


def test_connection_string_uses_comma_port(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "pyodbc",
                        types.SimpleNamespace(connect=lambda s, timeout: captured.setdefault("s", s)))
    line2.connect({"server": "10.0.0.5", "port": "49561", "database": "d", "username": "u", "password": "p"})
    assert "SERVER=10.0.0.5,49561;" in captured["s"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(line2, "DEMO_MODE", True)
    line2.poll_once()
    return line2.app.test_client()


def test_pages_and_api(client):
    status = client.get("/api/status").get_json()
    assert status["db_ok"] and len(status["stations"]) == 17
    st1 = client.get("/api/station/1").get_json()
    assert [t["tag"] for t in st1["tools"]] == ["T1", "T2", "T3"] and st1["tools"][0]["x"] == 16
    page = client.get("/station/5").get_data(as_text=True)
    assert "MAT513357TFJ12784" in page and "chassis/chassis-top.svg" in page and "setup-panel" in page
    assert client.get("/station/3").status_code == 200
    assert client.get("/station/18").status_code == 404
    assert client.get("/").status_code == 200
