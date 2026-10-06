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
    assert [(t["t_no"], t["x"], t["y"]) for t in tools] == [("T18", 16, 27), ("T23", 78.2, 73.3)]


def test_template_edits_are_picked_up_without_restart(tmp_path, monkeypatch):
    (tmp_path / "templates").mkdir()
    page = tmp_path / "templates" / "station_99.html"
    page.write_text('{% extends "station_base.html" %}{% set tools = [{"t_no": "t7", "x": 150, "y": 10}] %}')
    monkeypatch.setattr(line2.app, "root_path", str(tmp_path))
    cfg = line2.station_config(99)
    assert cfg["tools"] == [{"t_no": "T7", "name": "", "x": 100, "y": 10}] and cfg["chassis_image"] == "IMG_1.jpg"
    page.write_text('{% extends "station_base.html" %}{% set chassis_image = "IMG_3.jpg" %}'
                    '{% set tools = [{"t_no": "T8"}, {"x": 5}] %}')
    os.utime(page, (time.time() + 5, time.time() + 5))
    cfg = line2.station_config(99)
    assert cfg["tools"] == [{"t_no": "T8", "name": "", "x": None, "y": None}] and cfg["chassis_image"] == "IMG_3.jpg"


def test_build_station_statuses():
    mapping = {5: {"vc": "VC5", "mat": "MAT5"}}
    torques = {"T18": {"name": "ARB", "set": 4, "actual": 4, "bypass": True},
               "T23": {"name": "ARB 2", "set": 4, "actual": 1, "bypass": False}}
    st = line2.build_station(5, mapping, torques)
    assert (st["vc_number"], st["mat_number"], st["status"]) == ("VC5", "MAT5", "red")
    t18, t23 = st["tools"]
    assert (t18["status"], t18["mode"], t18["label"]) == ("OK", "BYPASS", "ARB bolt fitment")  # name from template
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
    assert "MAT513357TFJ12784" in page and "chassis/IMG_2.jpg" in page and "Manager login" in page and "edit-toggle" not in page
    assert client.get("/station/3").status_code == 200
    assert client.get("/station/18").status_code == 404
    home = client.get("/").get_data(as_text=True)
    assert "Background.jpg" in home and ">STN - 17<" in home


# ---------------- manager login + saving positions into the template ----------------

@pytest.fixture
def station_copy(tmp_path, monkeypatch):
    """Point the app at a copy of the templates so tests never modify the real files."""
    import shutil
    shutil.copytree(os.path.join(os.path.dirname(line2.__file__), "templates"), tmp_path / "templates")
    shutil.copytree(os.path.join(os.path.dirname(line2.__file__), "static"), tmp_path / "static")
    monkeypatch.setattr(line2.app, "root_path", str(tmp_path))
    monkeypatch.setattr(line2.app, "template_folder", str(tmp_path / "templates"))
    line2.app.jinja_env.loader.searchpath = [str(tmp_path / "templates")]
    line2._template_cache.clear()
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(line2, "MANAGERS", {"manager1": generate_password_hash("secret-pass")})
    yield tmp_path / "templates"
    line2.app.jinja_env.loader.searchpath = [os.path.join(os.path.dirname(line2.__file__), "templates")]
    line2._template_cache.clear()


def _csrf(client):
    with client.session_transaction() as s:
        s.setdefault("csrf", "test-token")
        return s["csrf"]


def test_save_positions_needs_login_and_rewrites_template(client, station_copy):
    body = {"positions": {"T18": {"x": 44.62, "y": 75.9}}}
    assert client.post("/api/station/5/positions", json=body).status_code == 401

    bad = client.post("/login", data={"username": "manager1", "password": "nope", "csrf_token": _csrf(client)})
    assert b"Wrong username or password" in bad.data
    ok = client.post("/login", data={"username": "Manager1", "password": "secret-pass",
                                     "csrf_token": _csrf(client), "next": "/station/5"})
    assert ok.headers["Location"] == "/station/5"
    assert "edit-toggle" in client.get("/station/5").get_data(as_text=True)
    assert client.post("/api/station/5/positions", json=body).status_code == 403  # no CSRF header

    res = client.post("/api/station/5/positions", json=body, headers={"X-CSRF-Token": _csrf(client)})
    assert res.status_code == 200, res.get_json()
    text = (station_copy / "station_5.html").read_text()
    assert '{"t_no": "T18", "name": "ARB bolt fitment", "x": 44.6, "y": 75.9},' in text   # name kept
    assert '{"t_no": "T23", "name": "Front/rear ARB", "x": 78.2, "y": 73.3},' in text   # untouched
    assert "positions last saved" in text and "by Manager1" in text
    assert "Station 5 - which torque wrenches" in text and 'chassis_image = "IMG_2.jpg"' in text  # rest kept
    assert (station_copy / "station_5.html.bak").exists()
    st5 = client.get("/api/station/5").get_json()
    assert [(t["tag"], t["x"], t["y"]) for t in st5["tools"]] == [("T18", 44.6, 75.9), ("T23", 78.2, 73.3)]

    # saving twice keeps a single "last saved" line
    client.post("/api/station/5/positions", json=body, headers={"X-CSRF-Token": _csrf(client)})
    assert (station_copy / "station_5.html").read_text().count("positions last saved") == 1

    bad_body = client.post("/api/station/5/positions", json={"positions": {"T18": {"x": "abc"}}},
                           headers={"X-CSRF-Token": _csrf(client)})
    assert bad_body.status_code == 400


def test_login_redirect_stays_on_site(client, station_copy):
    res = client.post("/login", data={"username": "manager1", "password": "secret-pass",
                                      "csrf_token": _csrf(client), "next": "//evil.example"})
    assert res.headers["Location"] == "/"
