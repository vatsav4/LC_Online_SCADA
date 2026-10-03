from datetime import datetime

import logdump as line2

RAW = ('{"Name":"ST08 50Nm T37 Steering pressure line to return lin", "MAT":"MAT513357TFJ12781", '
       '"Station No":"STATION 8","Operator":"","Mode":"ACTIVE","Set Count":+2,"Actual Count":+10,"Status":"OK"}')


def test_parse_payload_accepts_plus_signed_numbers():
    payload = line2.parse_payload(RAW)
    assert (payload["Set Count"], payload["Actual Count"], payload["Status"]) == (2, 10, "OK")


def test_parse_payload_falls_back_to_pairs_on_broken_json():
    payload = line2.parse_payload('{"Name":"ST5 T18", "Set Count":+4, "Status":"NOT OK"')
    assert payload == {"Name": "ST5 T18", "Set Count": 4, "Status": "NOT OK"}
    assert line2.parse_payload(None) == {} and line2.parse_payload("garbage") == {}


def test_tool_from_row():
    tool = line2.tool_from_row({"type_data": "T37", "data": RAW, "in_date_time": datetime(2026, 9, 29, 10)})
    assert tool["label"] == "Steering pressure line to return lin"
    assert (tool["station"], tool["torque_nm"], tool["set"], tool["actual"]) == (8, 50, 2, 10)
    assert tool["status"] == "OK"


def test_tool_status_falls_back_to_counts_when_status_missing():
    tool = line2.tool_from_row({"type_data": "T2", "data": '{"Name":"ST1 T2 Tail","Set Count":+5,"Actual Count":+3}'})
    assert tool["status"] == "NOT OK"


def _row(station, mat, tag=None, data=None):
    return {"StationNumber": station, "VC_Number": "VC", "MAT_Number": mat,
            "in_date_time": None, "type_data": tag, "data": data}


def _data(station, status):
    return f'{{"Name":"ST{station} T","Station No":"STATION {station}","Set Count":+1,"Actual Count":+1,"Status":"{status}"}}'


def test_build_stations_latest_per_tag_station_filter_and_pending():
    rows = [
        _row(1, "A", "T1", _data(1, "OK")),       # newest T1
        _row(1, "A", "T1", _data(1, "NOT OK")),   # older T1, ignored
        _row(1, "A", "T9", _data(3, "NOT OK")),   # logged at another station, ignored
        _row(2, "B"),                             # no data yet
        _row(3, "C", "T5", _data(3, "NOT OK")),
    ]
    stations = line2.build_stations(rows, {2: ["T7"]})
    assert [stations[n]["status"] for n in (1, 2, 3)] == ["green", "red", "red"]
    assert [t["tag"] for t in stations[1]["tools"]] == ["T1"]
    assert stations[2]["tools"][0]["status"] == "PENDING"
