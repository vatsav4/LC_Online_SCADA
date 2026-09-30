import asyncio
import os
import sys
import threading
import time
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "line2_dashboard"))

from opcua_source import OpcUaSource, build_stations_from_tags, load_tag_map  # noqa: E402

EXAMPLE_MAP = os.path.join(os.path.dirname(__file__), "..", "line2_dashboard", "tag_map.csv.example")


def test_example_tag_map_loads():
    rows = load_tag_map(EXAMPLE_MAP)
    assert {r["station"] for r in rows} == {1, 8}
    assert all(r["node_id"].startswith("ns=2;s=") for r in rows)


def test_load_tag_map_rejects_bad_kind(tmp_path):
    bad = tmp_path / "m.csv"
    bad.write_text("station,kind,tool,node_id,label,torque_nm\n1,speed,T1,ns=2;s=x,,\n")
    with pytest.raises(ValueError):
        load_tag_map(str(bad))


def _map():
    return [
        {"station": 1, "kind": "mat", "tool": "", "node_id": "mat1", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "set", "tool": "T1", "node_id": "s1", "label": "SG Tightening", "torque_nm": "35"},
        {"station": 1, "kind": "actual", "tool": "T1", "node_id": "a1", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "status", "tool": "T1", "node_id": "ok1", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "mode", "tool": "T1", "node_id": "by1", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "set", "tool": "T2", "node_id": "s2", "label": "Tail", "torque_nm": ""},
        {"station": 1, "kind": "actual", "tool": "T2", "node_id": "a2", "label": "", "torque_nm": ""},
        {"station": 2, "kind": "set", "tool": "T5", "node_id": "s5", "label": "", "torque_nm": ""},
    ]


def test_build_stations_from_tags():
    values = {"mat1": "MAT123  ", "s1": 5, "a1": 5, "ok1": True, "by1": 1, "s2": 5, "a2": 3}
    st = build_stations_from_tags(_map(), values, {"a1": datetime(2026, 9, 30, 9)},
                                  mapping={1: {"vc_number": "VC1", "mat_number": "ignored"}})
    one = st[1]
    assert (one["mat_number"], one["vc_number"]) == ("MAT123", "VC1")  # tag wins, SQL fills the gap
    t1, t2 = one["tools"]
    assert (t1["status"], t1["mode"], t1["torque_nm"], t1["updated"]) == ("OK", "BYPASS", 35, "30-09-2026 09:00:00")
    assert t2["status"] == "NOT OK"          # no status tag -> actual < set
    assert one["status"] == "red"
    assert st[2]["tools"][0]["status"] == "PENDING" and st[2]["status"] == "red"


def test_status_values_are_configurable():
    values = {"s1": 1, "a1": 1, "ok1": "NOT OK", "s2": 1, "a2": 1}
    st = build_stations_from_tags(_map(), values)
    assert st[1]["tools"][0]["status"] == "NOT OK"
    values["ok1"] = 2
    st = build_stations_from_tags(_map(), values, ok_values=("2",))
    assert st[1]["tools"][0]["status"] == "OK"


def test_live_subscription_against_local_opcua_server():
    """End-to-end: a real OPC UA server, our subscriber, and a value change pushed by the server."""
    from asyncua import Server

    ready, stop = threading.Event(), threading.Event()
    box = {}

    async def serve():
        server = Server()
        await server.init()
        server.set_endpoint("opc.tcp://127.0.0.1:48410/test/")
        ns = await server.register_namespace("urn:line2:test")
        st1 = await server.nodes.objects.add_object(ns, "ST01")
        box["actual"] = await st1.add_variable(f"ns={ns};s=Line2.ST01.T1.ActualCount", "ActualCount", 0)
        await st1.add_variable(f"ns={ns};s=Line2.ST01.T1.SetCount", "SetCount", 5)
        await st1.add_variable(f"ns={ns};s=Line2.ST01.MAT", "MAT", "MAT784062TFJ12788")
        box["ns"] = ns
        async with server:
            ready.set()
            while not stop.is_set():
                if "new_actual" in box:
                    await box["actual"].write_value(box.pop("new_actual"))
                await asyncio.sleep(0.05)

    threading.Thread(target=lambda: asyncio.run(serve()), daemon=True).start()
    assert ready.wait(10)
    ns = box["ns"]
    tag_map = [
        {"station": 1, "kind": "mat", "tool": "", "node_id": f"ns={ns};s=Line2.ST01.MAT", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "set", "tool": "T1", "node_id": f"ns={ns};s=Line2.ST01.T1.SetCount", "label": "SG", "torque_nm": ""},
        {"station": 1, "kind": "actual", "tool": "T1", "node_id": f"ns={ns};s=Line2.ST01.T1.ActualCount", "label": "", "torque_nm": ""},
        {"station": 1, "kind": "actual", "tool": "T9", "node_id": f"ns={ns};s=DoesNotExist", "label": "", "torque_nm": ""},
    ]
    src = OpcUaSource("opc.tcp://127.0.0.1:48410/test/", [r["node_id"] for r in tag_map],
                      publishing_interval_ms=100, retry_seconds=1).start()

    def wait_for(pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            values, updated, connected = src.snapshot()
            stations = build_stations_from_tags(tag_map, values, updated)
            if connected and pred(stations[1]):
                return stations[1]
            time.sleep(0.1)
        raise AssertionError(f"timed out; last: {stations[1]}")

    try:
        st = wait_for(lambda s: s["mat_number"] and s["tools"][0]["actual"] == 0)
        assert st["mat_number"] == "MAT784062TFJ12788"
        assert st["tools"][0]["status"] == "NOT OK"          # 0 < 5
        assert st["tools"][1]["status"] == "PENDING"         # bad node id doesn't break the rest

        box["new_actual"] = 5                                # SCADA value changes -> pushed to us
        st = wait_for(lambda s: s["tools"][0]["actual"] == 5)
        assert st["tools"][0]["status"] == "OK"
    finally:
        src.stop()
        stop.set()
