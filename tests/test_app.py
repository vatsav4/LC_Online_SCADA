import os
import shutil
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
            assert (t["t_no"].startswith("T") or line2._UBOLT.match(t["t_no"])), t["t_no"]
            assert t["x"] is None or (0 <= t["x"] <= 100 and 0 <= t["y"] <= 100)


STATION_5 = """{% extends "station_base.html" %}
{# Station 5 - which torque wrenches are shown on this station's page. #}
{% set chassis_image = "IMG_2.jpg" %}
{% set tools = [
    {"t_no": "T18", "name": "ARB bolt fitment", "x": 16, "y": 27},
    {"t_no": "T23", "name": "Front/rear ARB", "x": 78.2, "y": 73.3},
] %}
"""

STATION_7 = """{% extends "station_base.html" %}
{% set tools = [] %}
{% set s3_controls = [
    {"tag": "Inversion_Light_Curtain_LH", "name": "Light Curtain LH"},
    {"tag": "Inversion_Over_Travel"},
    {"tag": "Door_Switch_RH", "name": "Door", "picture": "sensor"},
    {"tag": "Curtain_Reversed", "name": "Reversed", "ok_value": 1},
] %}
"""


@pytest.fixture
def known_templates(tmp_path, monkeypatch):
    """Stations 5 and 7 with fixed contents, so tests don't depend on the real (edited) templates."""
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "station_5.html").write_text(STATION_5)
    (tmp_path / "templates" / "station_7.html").write_text(STATION_7)
    shutil.copy(os.path.join(TEMPLATES, "station_generic.html"), tmp_path / "templates")
    monkeypatch.setattr(line2.app, "root_path", str(tmp_path))
    line2._template_cache.clear()
    yield tmp_path / "templates"
    line2._template_cache.clear()


def test_station_template_lists_its_wrenches_and_s3_controls(known_templates):
    tools = line2.station_config(5)["tools"]
    assert [(t["t_no"], t["x"], t["y"]) for t in tools] == [("T18", 16, 27), ("T23", 78.2, 73.3)]
    s3 = line2.station_config(7)["s3_controls"]
    assert s3 == [
        {"tag": "INVERSION_LIGHT_CURTAIN_LH", "name": "Light Curtain LH", "picture": "light_curtain", "place": "top", "ok_value": 0},
        {"tag": "INVERSION_OVER_TRAVEL", "name": "Inversion Over Travel", "picture": "over_travel", "place": "top", "ok_value": 0},
        {"tag": "DOOR_SWITCH_RH", "name": "Door", "picture": "sensor", "place": "bottom", "ok_value": 0},
        {"tag": "CURTAIN_REVERSED", "name": "Reversed", "picture": "sensor", "place": "top", "ok_value": 1},
    ]


def test_template_mistake_does_not_break_home_page(known_templates, client):
    (known_templates / "station_5.html").write_text(STATION_5.replace("] %}", "<!-- x --> ] %}"))
    cfg = line2.station_config(5)
    assert cfg["tools"] == [] and "station_5.html line" in cfg["error"]
    assert client.get("/api/status").status_code == 200
    with pytest.raises(ValueError):
        line2.save_positions(5, {}, "someone")   # never overwrite a broken template

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


def test_build_station_statuses(known_templates):
    mapping = {5: {"vc": "VC5", "mat": "MAT5"}}
    torques = {"T18": {"name": "ARB", "set": 4, "actual": 4, "bypass": True},
               "T23": {"name": "ARB 2", "set": 4, "actual": 1, "bypass": False}}
    st = line2.build_station(5, mapping, torques)
    assert (st["vc_number"], st["mat_number"], st["status"]) == ("VC5", "MAT5", "red")
    t18, t23 = st["tools"]
    assert (t18["status"], t18["label"]) == ("OK", "ARB bolt fitment")  # name from template
    assert "mode" not in t18   # bypass is not shown anywhere for now
    assert t23["status"] == "NOT OK"
    assert line2.build_station(5, mapping, {})["tools"][0]["status"] == "PENDING"
    assert line2.build_station(3, mapping, torques)["status"] == "idle"   # no template, nothing to check


def test_set_count_zero_hides_the_wrench(known_templates):
    torques = {"T18": {"name": "", "set": 0, "actual": 0, "bypass": False},     # not used for this model
               "T23": {"name": "", "set": 4, "actual": 4, "bypass": False}}
    st = line2.build_station(5, {}, torques)
    assert [t["hidden"] for t in st["tools"]] == [True, False] and st["status"] == "green"
    summary = line2._summary([st])[0]
    assert (summary["l3_ok"], summary["l3_total"], summary["l3_skipped"]) == (1, 1, 1)
    torques["T23"]["set"] = 0
    st = line2.build_station(5, {}, torques)
    assert st["status"] == "idle" and line2._summary([st])[0]["l3_total"] == 0
    assert not line2.build_station(5, {}, {})["tools"][0]["hidden"]   # no data yet: shown as awaiting


def test_s3_status_1_is_not_ok(known_templates):
    from datetime import datetime
    s3 = {"INVERSION_LIGHT_CURTAIN_LH": {"value": 1, "changed": datetime.now()},
          "INVERSION_OVER_TRAVEL": {"value": 0, "changed": None},
          "CURTAIN_REVERSED": {"value": 0, "changed": None}}          # ok_value 1: 0 is NOT OK
    st = line2.build_station(7, {}, {}, s3)
    assert [c["status"] for c in st["s3"]] == ["NOT OK", "OK", "PENDING", "NOT OK"] and st["status"] == "red"
    s3["CURTAIN_REVERSED"]["value"] = 1
    assert st["s3"][0]["since"].count(":") == 2
    s3["INVERSION_LIGHT_CURTAIN_LH"]["value"] = 0
    s3["DOOR_SWITCH_RH"] = {"value": 0, "changed": None}
    assert line2.build_station(7, {}, {}, s3)["status"] == "green"
    summary = line2._summary([line2.build_station(7, {}, {}, s3)])[0]
    assert (summary["l3_total"], summary["s3_ok"], summary["s3_total"]) == (0, 4, 4)


def test_fetch_tables_reads_both_tables():
    results = [[(1, "VC1 ", "MAT1")], [("t1 ", " SG ", 5, 3, 1), (None, "", 0, 0, 0)],
               [("Inversion_Over_Travel", True, None), ("X", None, None)],
               [("lh", "MAT1 ", 270, 270.3, 270.4, 270.6, None, 0, 1, 2, 3, 4)],
               [("RH", "MAT2", 400, 401, 402, 403, 404, 405, 406, 0, 0, 0, 0, 0, None)]]
    class Cur:
        def execute(self, sql):
            self.rows = results.pop(0)
        def fetchall(self):
            return self.rows
    conn = types.SimpleNamespace(cursor=lambda: Cur())
    mapping, torques, s3, ubolts, wheels = line2.fetch_tables(conn)
    assert mapping == {1: {"vc": "VC1", "mat": "MAT1"}}
    assert torques == {"T1": {"name": "SG", "set": 5, "actual": 3, "bypass": True}}
    assert s3 == {"INVERSION_OVER_TRAVEL": {"value": 1, "changed": None}, "X": {"value": None, "changed": None}}
    assert ubolts == {("MAT1", "LH"): {"mat": "MAT1", "front_set": 270, "rear_set": 270.3,
                                       "front": [270.4, 270.6, None, 0], "rear": [1, 2, 3, 4]}}
    assert wheels == {"RH": {"mat": "MAT2", "front_set": 400, "rear_set": 400,
                             "front": [401, 402, 403, 404, 405, 406], "rear": [0, 0, 0, 0, 0, None]}}


def test_wheel_groups_have_six_nuts(known_templates):
    (known_templates / "station_15.html").write_text(
        '{% extends "station_base.html" %}{% set tools = [{"t_no": "WHEEL_LH_FRONT", "name": ""},'
        ' {"t_no": "WHEEL_RH_REAR", "name": "RH Rear"}] %}')
    wheels = {"LH": {"mat": "M1", "front_set": 400, "rear_set": 400, "front": [401, 400, 400.5, 402, 400, 401],
                     "rear": [0] * 6},
              "RH": {"mat": "M1", "front_set": 400, "rear_set": 400, "front": [0] * 6, "rear": [400, 0, 0, 0, 0, 0]}}
    lf, rr = line2.build_station(15, {15: {"vc": "", "mat": "M1"}}, {}, {}, {}, wheels)["tools"]
    assert (lf["label"], lf["nut_count"], lf["status"], lf["done"]) == ("LH Front Wheel", 6, "OK", 6)
    assert (rr["short"], rr["status"], rr["done"]) == ("RR", "NOT OK", 1)
    # the fixed U-bolt set torque doesn't touch wheels, and wheels still need the station's MAT
    wheels["LH"]["front_set"] = 999
    assert line2.build_station(15, {15: {"vc": "", "mat": "M1"}}, {}, {}, {}, wheels)["tools"][0]["set"] == 999
    assert line2.build_station(15, {15: {"vc": "", "mat": "M2"}}, {}, {}, {}, wheels)["tools"][0]["note"] == "other vehicle"


def test_ubolt_groups_show_the_vehicle_at_the_station(known_templates):
    (known_templates / "station_6.html").write_text(
        '{% extends "station_base.html" %}{% set tools = [{"t_no": "ubolt_lh_front", "name": "LH Front"},'
        ' {"t_no": "UBOLT_RH_REAR", "name": ""}] %}')
    # one row per vehicle (MAT) and side; MAT8 is the vehicle before, already done
    ubolts = {("MAT9", "LH"): {"mat": "MAT9", "front_set": 999, "rear_set": 270.3, "front": [270.4, 270, 269.9, None],
                               "rear": [None] * 4},
              ("MAT9", "RH"): {"mat": "MAT9", "front_set": 270, "rear_set": 270.3, "front": [None] * 4, "rear": [270.3] * 4},
              ("MAT8", "LH"): {"mat": "MAT8", "front_set": 270, "rear_set": 270.3, "front": [271] * 4, "rear": [271] * 4}}
    st = line2.build_station(6, {6: {"vc": "", "mat": "mat9"}}, {}, {}, ubolts)
    lf, rr = st["tools"]
    assert (lf["short"], lf["set"], lf["status"]) == ("LF", 270, "NOT OK")      # set torque always 270
    assert [n["state"] for n in lf["nuts"]] == ["ok", "ok", "bad", "pending"]
    assert (rr["short"], rr["label"], rr["status"], rr["done"]) == ("RR", "RH Rear U-bolt", "OK", 4)
    # the vehicle before (MAT8) at the station: its own values
    lf8 = line2.build_station(6, {6: {"vc": "", "mat": "MAT8"}}, {}, {}, ubolts)["tools"][0]
    assert (lf8["status"], [n["value"] for n in lf8["nuts"]]) == ("OK", [271] * 4)
    # a vehicle with nothing logged yet / no MAT at the station
    assert line2.build_station(6, {6: {"vc": "", "mat": "MAT7"}}, {}, {}, ubolts)["tools"][0]["note"] == "awaiting data"
    assert line2.build_station(6, {}, {}, {}, ubolts)["tools"][0]["note"] == "no MAT at station"


def test_missing_s3_table_does_not_stop_torques():
    class Cur:
        def execute(self, sql):
            raise RuntimeError("Invalid object name 'dbo.S3_Controls_Data'")
    assert line2.fetch_s3(types.SimpleNamespace(cursor=lambda: Cur())) == {}


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
    for n in range(1, 18):
        page = client.get(f"/station/{n}")
        assert page.status_code == 200 and b"template-error" not in page.data, n
    page = client.get("/station/5").get_data(as_text=True)
    assert "MAT513357TFJ12784" in page and "chassis/IMG_2.jpg" in page and "Manager login" in page and "edit-toggle" not in page
    st7 = client.get("/api/station/7").get_json()
    assert len(st7["s3"]) == 3 and "s3-rays" in client.get("/station/7").get_data(as_text=True)
    assert client.get("/station/18").status_code == 404
    assert "BYPASS" not in client.get("/station/10").get_data(as_text=True)
    assert "User-Agent" not in client.get("/display-check").get_data(as_text=True)
    assert client.get("/display-check").status_code == 200
    home = client.get("/").get_data(as_text=True)
    assert "Background.jpg" in home and ">STN - 17<" in home


# ---------------- manager login + saving positions into the template ----------------

@pytest.fixture
def station_copy(tmp_path, monkeypatch):
    """Point the app at a copy of the templates so tests never modify the real files."""
    shutil.copytree(os.path.join(os.path.dirname(line2.__file__), "templates"), tmp_path / "templates")
    shutil.copytree(os.path.join(os.path.dirname(line2.__file__), "static"), tmp_path / "static")
    monkeypatch.setattr(line2.app, "root_path", str(tmp_path))
    monkeypatch.setattr(line2.app, "template_folder", str(tmp_path / "templates"))
    line2.app.jinja_env.loader.searchpath = [str(tmp_path / "templates")]
    line2._template_cache.clear()
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(line2, "MANAGERS", {"manager1": generate_password_hash("secret-pass")})
    (tmp_path / "templates" / "station_5.html").write_text(STATION_5)
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
