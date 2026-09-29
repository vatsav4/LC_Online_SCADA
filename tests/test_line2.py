from datetime import datetime

from line2_dashboard import db
from line2_dashboard.parser import parse_payload, station_of, to_record
from line2_dashboard.service import build_stations, summarize

RAW = ('{"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781", '
       '"Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}')


def test_parse_payload_accepts_plus_signed_numbers():
    payload = parse_payload(RAW)
    assert payload["Set Count"] == 2
    assert payload["Actual Count"] == 10
    assert payload["Status"] == "OK"


def test_parse_payload_falls_back_to_pairs_on_broken_json():
    payload = parse_payload('{"Name":"ST5 T18", "Set Count":+4, "Status":"NOT OK"')
    assert payload == {"Name": "ST5 T18", "Set Count": 4, "Status": "NOT OK"}


def test_parse_payload_handles_empty_and_garbage():
    assert parse_payload(None) == {}
    assert parse_payload("not json") == {}


def test_station_of_prefers_station_no_then_name():
    assert station_of({"Station No": "STATION 10"}) == 10
    assert station_of({"Name": "ST02 86Nm T39"}) == 2
    assert station_of({}) is None


def test_to_record_extracts_fields():
    rec = to_record({"id": 1, "in_date_time": datetime(2026, 9, 29, 10, 0), "mat_no": "MAT1  ",
                     "type_data": "T37", "data": RAW})
    assert rec["station"] == 8
    assert rec["torque_nm"] == 50
    assert rec["mode"] == "ACTIVE"
    assert rec["time"] == "2026-09-29 10:00:00"


def _row(station, mat, tag=None, data=None, t=None):
    return {"StationNumber": station, "VC_Number": "VC", "MAT_Number": mat, "id": None,
            "in_date_time": t, "mat_no": mat if tag else None, "type_data": tag, "data": data}


def _data(station, status, mode="ACTIVE"):
    return (f'{{"Name":"ST{station} 10Nm", "Station No":"STATION {station}", "Mode":"{mode}",'
            f'"Set Count":+1,"Actual Count":+1,"Status":"{status}"}}')


def test_build_stations_keeps_latest_per_tag_and_filters_station():
    rows = [
        _row(1, "A", "T1", _data(1, "OK"), datetime(2026, 1, 1, 10)),       # latest T1
        _row(1, "A", "T1", _data(1, "NOT OK"), datetime(2026, 1, 1, 9)),    # older, ignored
        _row(1, "A", "T2", _data(3, "NOT OK", "BYPASS"), datetime(2026, 1, 1, 8)),  # other station
        _row(2, "B"),                                                        # no data yet
        _row(3, "C", "T5", _data(3, "NOT OK"), datetime(2026, 1, 1, 7)),
    ]
    stations = build_stations(rows)
    assert [s["status"] for s in stations] == ["OK", "WAITING", "NOT OK"]
    assert [r["tag"] for r in stations[0]["records"]] == ["T1"]
    assert summarize(stations) == {"stations": 3, "ok": 1, "not_ok": 1, "waiting": 1, "bypass": 0}

    loose = build_stations(rows, strict_station_match=False)
    assert loose[0]["status"] == "NOT OK"


def test_pyodbc_connection_string_uses_comma_port(monkeypatch):
    import sys
    import types

    captured = {}
    fake = types.SimpleNamespace(connect=lambda s, timeout: captured.setdefault("s", s))
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    monkeypatch.setattr(db.config, "DB_BACKEND", "pyodbc")
    monkeypatch.setattr(db.config, "DB_HOST", "10.0.0.5")
    monkeypatch.setattr(db.config, "DB_PORT", 49561)
    db.connect()
    assert "SERVER=10.0.0.5,49561;" in captured["s"]


def test_api_in_demo_mode(monkeypatch):
    from line2_dashboard import app as app_module

    monkeypatch.setattr(db.config, "DEMO_MODE", True)
    client = app_module.app.test_client()
    snap = client.get("/api/line").get_json()
    assert snap["summary"]["stations"] == 14
    st5 = next(s for s in snap["stations"] if s["station"] == 5)
    assert st5["status"] == "NOT OK" and {r["tag"] for r in st5["records"]} == {"T18", "T23"}
    st14 = next(s for s in snap["stations"] if s["station"] == 14)
    assert st14["status"] == "OK"  # padded mat_no still matched
    assert len(client.get("/api/events?limit=5").get_json()["events"]) == 5
    assert client.get("/").status_code == 200
