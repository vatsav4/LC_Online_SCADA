import io
import json
import sys
import types

import pytest

import app as line2
import auth
import demo_data
import layouts
import torques

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


# ---------------- torques source ----------------

def test_torque_rows_become_tools():
    ok = torques.tool_from_row("T1", {"T_No": "T1", "T_Name": " SG ", "Set_Counts": 5, "Actual_Counts": 5,
                                      "Active_Bypass": 0})
    bad = torques.tool_from_row("T2", {"T_No": "T2", "T_Name": "Tail", "Set_Counts": 5, "Actual_Counts": 3,
                                       "Active_Bypass": True})
    assert (ok["status"], ok["mode"], ok["label"]) == ("OK", "ACTIVE", "SG")
    assert (bad["status"], bad["mode"]) == ("NOT OK", "BYPASS")
    assert torques.tool_from_row("T9", None)["status"] == "PENDING"


def test_stations_get_their_wrenches_from_the_layout():
    mapping = [{"StationNumber": 1, "VC_Number": "VC1 ", "MAT_Number": "MAT1"},
               {"StationNumber": 2, "VC_Number": "VC2", "MAT_Number": "MAT2"}]
    rows = [{"T_No": "t1", "T_Name": "SG", "Set_Counts": 5, "Actual_Counts": 5, "Active_Bypass": 0}]
    lay = {1: {"image": "chassis-top.svg", "tools": [{"t_no": "T1", "x": 0.2, "y": 0.7, "label": ""},
                                                     {"t_no": "T7", "x": None, "y": None, "label": "New"}]}}
    st = torques.build_stations(mapping, rows, lay)
    assert st[1]["vc_number"] == "VC1" and [t["tag"] for t in st[1]["tools"]] == ["T1", "T7"]
    assert st[2]["tools"] == []
    layouts.apply(st, lay, "chassis-top.svg")
    t1, t7 = st[1]["tools"]
    assert (t1["x"], t1["y"], t1["label"], t1["status"]) == (0.2, 0.7, "SG", "OK")
    assert (t7["x"], t7["label"], t7["status"]) == (None, "New", "PENDING")
    assert st[1]["status"] == "red" and st[2]["status"] == "idle"
    assert st[1]["layout"]["tools"][0]["t_no"] == "T1"


def test_all_tool_numbers_sorted_naturally():
    rows = [{"T_No": n} for n in ("T10", "T2", "T1", " ")]
    assert torques.all_tool_numbers(rows) == ["T1", "T2", "T10"]


# ---------------- layouts ----------------

def test_validate_cleans_and_rejects():
    clean = layouts.validate({"image": "chassis-top.svg", "tools": [
        {"t_no": "t3", "x": 1.7, "y": -1, "label": "x" * 200},
        {"t_no": "T4", "x": 0.5, "y": None}]})
    assert clean["tools"][0] == {"t_no": "T3", "x": 1.0, "y": 0.0, "label": "x" * 80}
    assert clean["tools"][1]["x"] is None  # half a position = not placed
    for bad in ({"image": "nope.png", "tools": []},
                {"image": "chassis-top.svg", "tools": [{"t_no": "T1"}, {"t_no": "t1"}]},
                {"image": "chassis-top.svg", "tools": [{"t_no": "../etc"}]},
                {"image": "chassis-top.svg", "tools": [{"t_no": "T1", "x": "abc", "y": 1}]}):
        with pytest.raises(ValueError):
            layouts.validate(bad)


def test_image_path_blocks_traversal():
    assert layouts.image_path("chassis-top.svg")
    assert layouts.image_path("../app.py") is None
    assert layouts.image_path("..") is None


def test_upload_accepts_only_real_pictures():
    name = layouts.save_upload("My Chassis.png", PNG)
    assert name.startswith("My-Chassis-") and name.endswith(".png")
    assert layouts.image_path(name)
    with pytest.raises(ValueError):
        layouts.save_upload("evil.svg", b"<svg onload=alert(1)>")
    with pytest.raises(ValueError):
        layouts.save_upload("fake.png", b"MZ not a png")


# ---------------- app: pages, login, editor ----------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(line2, "DEMO_MODE", True)
    monkeypatch.setattr(line2, "SOURCE", "torques")
    auth.set_password("manager1", "secret-pass")
    line2.poll_once()
    return line2.app.test_client()


def _csrf(client):
    with client.session_transaction() as s:
        s.setdefault("csrf", "test-token")
        return s["csrf"]


def _login(client):
    token = _csrf(client)
    return client.post("/login", data={"username": "manager1", "password": "secret-pass",
                                       "csrf_token": token, "next": "/station/1"})


def test_pages_render_for_everyone(client):
    status = client.get("/api/status").get_json()
    assert status["db_ok"] and len(status["stations"]) == 14
    st1 = client.get("/api/station/1").get_json()
    assert [t["tag"] for t in st1["tools"]] == ["T1", "T2", "T3"]
    assert st1["tools"][0]["x"] == 0.16 and st1["image"] == "chassis-top.svg"
    assert st1["can_edit"] is False
    page = client.get("/station/1").get_data(as_text=True)
    assert "station-data" in page and "Manager login" in page and "edit-toggle" not in page
    assert client.get("/chassis/chassis-top.svg").status_code == 200
    assert client.get("/chassis/..%2Fapp.py").status_code == 404


def test_editing_needs_login_and_csrf(client):
    body = {"image": "chassis-top.svg", "tools": [{"t_no": "T5", "x": 0.3, "y": 0.4, "label": "Test"}]}
    assert client.post("/api/layout/3", json=body).status_code == 401
    assert client.get("/api/editor").status_code == 401

    bad = client.post("/login", data={"username": "manager1", "password": "wrong",
                                      "csrf_token": _csrf(client)})
    assert b"Wrong username or password" in bad.data

    assert _login(client).headers["Location"] == "/station/1"
    assert client.post("/api/layout/3", json=body).status_code == 403  # no CSRF header
    token = _csrf(client)
    assert "edit-toggle" in client.get("/station/3").get_data(as_text=True)

    editor = client.get("/api/editor", headers={"X-CSRF-Token": token}).get_json()
    assert "T1" in editor["tools"] and editor["assigned"]["T1"] == 1
    assert any(i["name"] == "chassis-top.svg" for i in editor["images"])

    res = client.post("/api/layout/3", json=body, headers={"X-CSRF-Token": token})
    assert res.status_code == 200 and res.get_json()["layout"]["updated_by"] == "manager1"
    st3 = client.get("/api/station/3").get_json()
    assert [(t["tag"], t["label"], t["x"]) for t in st3["tools"]] == [("T5", "Test", 0.3)]
    assert st3["layout_updated"].endswith("by manager1")

    bad_layout = client.post("/api/layout/3", json={"image": "x.png", "tools": []},
                             headers={"X-CSRF-Token": token})
    assert bad_layout.status_code == 400

    up = client.post("/api/chassis-images", headers={"X-CSRF-Token": token},
                     data={"image": (io.BytesIO(PNG), "line2.png")}, content_type="multipart/form-data")
    assert up.status_code == 200 and up.get_json()["name"].endswith(".png")

    client.post("/logout", data={"csrf_token": token, "next": "https://evil.example"})
    assert client.get("/api/editor").status_code == 401


def test_open_redirect_blocked(client):
    res = client.post("/login", data={"username": "manager1", "password": "secret-pass",
                                      "csrf_token": _csrf(client), "next": "//evil.example"})
    assert res.headers["Location"] == "/"


def test_logdump_source_still_works(monkeypatch):
    monkeypatch.setattr(line2, "DEMO_MODE", True)
    monkeypatch.setattr(line2, "SOURCE", "logdump")
    line2.poll_once()
    st5 = line2.app.test_client().get("/api/station/5").get_json()
    assert {t["tag"] for t in st5["tools"]} == {"T18", "T23"} and st5["status"] == "red"


def test_connection_string_uses_comma_port(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "pyodbc",
                        types.SimpleNamespace(connect=lambda s, timeout: captured.setdefault("s", s)))
    line2.connect({"server": "10.0.0.5", "port": "49561", "database": "d", "username": "u", "password": "p"})
    assert "SERVER=10.0.0.5,49561;" in captured["s"]


def test_demo_rows_match_example_layout():
    example = json.load(open(layouts.EXAMPLE_FILE))["stations"]
    known = {r["T_No"] for r in demo_data.torque_rows()}
    assert all(t["t_no"] in known for st in example.values() for t in st["tools"])
