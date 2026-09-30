"""
Read Line-2 station/tool status straight from the SCADA's OPC UA server.

Designed to put as little load on the SCADA as possible:
  - ONE session and ONE subscription for the whole dashboard, however many
    browsers are open (pages only read the in-memory snapshot in app.py).
  - Report-by-exception: the SCADA pushes a value only when it changes,
    sampled no faster than `publishing_interval_ms`. No polling of tags.
  - Read-only: nothing is ever written back to the SCADA.
  - On disconnect it waits `retry_seconds` before reconnecting (no hammering).

Which SCADA tag feeds which box is defined in tag_map.csv (see tag_map.csv.example):

    station,kind,tool,node_id,label,torque_nm
    1,vc,,ns=2;s=Line2.ST01.VC_Number,,
    1,mat,,ns=2;s=Line2.ST01.MAT_Number,,
    1,set,T1,ns=2;s=Line2.ST01.T1.SetCount,SG Tightening,
    1,actual,T1,ns=2;s=Line2.ST01.T1.ActualCount,,
    1,status,T1,ns=2;s=Line2.ST01.T1.OK,,
    1,mode,T1,ns=2;s=Line2.ST01.T1.Bypass,,

kind: vc | mat | set | actual | status | mode. A tool's status tag is optional
(without it the tool is red while Actual < Set, same as the andon dashboard).
"""

import asyncio
import csv
import logging
import threading
from datetime import datetime

logger = logging.getLogger("LINE2_OPCUA")
logging.getLogger("asyncua").setLevel(logging.WARNING)  # asyncua is very chatty at INFO

KINDS = {"vc", "mat", "set", "actual", "status", "mode"}


# ================= TAG MAP =================

def load_tag_map(path):
    """Parse tag_map.csv into a list of dict rows. Raises ValueError on bad rows."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for line_no, row in enumerate(csv.DictReader(f), start=2):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not row.get("station") or row["station"].startswith("#"):
                continue
            kind = row.get("kind", "").lower()
            if kind not in KINDS:
                raise ValueError(f"{path}:{line_no}: kind must be one of {sorted(KINDS)}")
            if kind in ("set", "actual", "status", "mode") and not row.get("tool"):
                raise ValueError(f"{path}:{line_no}: '{kind}' rows need a tool (e.g. T1)")
            if not row.get("node_id"):
                raise ValueError(f"{path}:{line_no}: node_id is empty")
            rows.append({
                "station": int(row["station"]),
                "kind": kind,
                "tool": row.get("tool", ""),
                "node_id": row["node_id"],
                "label": row.get("label", ""),
                "torque_nm": row.get("torque_nm", ""),
            })
    return rows


# ================= VALUE -> UI MODEL =================

def _truthy(value, accepted):
    """True if value matches one of `accepted` (compared case-insensitively as text)."""
    if value is None:
        return False
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    return text.strip().lower() in accepted


def _number(value):
    if value is None or isinstance(value, bool):
        return None if value is None else int(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def _tag_key(tag):
    digits = "".join(ch for ch in tag if ch.isdigit())
    return (int(digits) if digits else 10**9, tag)


def build_stations_from_tags(tag_map, values, updated=None, mapping=None,
                             ok_values=("1", "true", "ok"), bypass_values=("1", "true", "bypass")):
    """Turn the latest tag values into the same station dicts the SQL source produces.

    values:  {node_id: value}  (a node missing from values has not reported yet)
    updated: {node_id: datetime} of the last change
    mapping: optional {station: {"vc_number", "mat_number"}} (e.g. from SQL) used when
             the tag map has no vc/mat tag for a station.
    """
    ok_values = {v.lower() for v in ok_values}
    bypass_values = {v.lower() for v in bypass_values}
    updated = updated or {}
    mapping = mapping or {}

    stations = {}
    for row in tag_map:
        st = stations.setdefault(row["station"], {"station": row["station"], "vc": None, "mat": None, "tools": {}})
        if row["kind"] in ("vc", "mat"):
            st[row["kind"]] = row["node_id"]
            continue
        tool = st["tools"].setdefault(row["tool"], {"nodes": {}, "label": "", "torque_nm": ""})
        tool["nodes"][row["kind"]] = row["node_id"]
        tool["label"] = tool["label"] or row["label"]
        tool["torque_nm"] = tool["torque_nm"] or row["torque_nm"]
    for number in mapping:
        stations.setdefault(number, {"station": number, "vc": None, "mat": None, "tools": {}})

    def text(node_id, fallback):
        if node_id is None:
            return fallback
        value = values.get(node_id)
        return str(value).strip() if value is not None else ""

    result = {}
    for number, st in stations.items():
        mapped = mapping.get(number, {})
        tools = []
        for tag, tool in st["tools"].items():
            nodes = tool["nodes"]
            set_count = _number(values.get(nodes.get("set")))
            actual = _number(values.get(nodes.get("actual")))
            reported = [values[n] for n in nodes.values() if values.get(n) is not None]
            if not reported:
                status = "PENDING"
            elif "status" in nodes:
                raw = values.get(nodes["status"])
                status = "PENDING" if raw is None else ("OK" if _truthy(raw, ok_values) else "NOT OK")
            else:
                status = "NOT OK" if set_count is not None and (actual or 0) < set_count else "OK"
            stamps = [updated[n] for n in nodes.values() if n in updated]
            last = max(stamps) if stamps else None
            tools.append({
                "tag": tag,
                "label": tool["label"] or ("Awaiting data" if status == "PENDING" else tag),
                "torque_nm": _number(tool["torque_nm"]) if tool["torque_nm"] else None,
                "station": number,
                "mode": "BYPASS" if _truthy(values.get(nodes.get("mode")), bypass_values) else
                        ("ACTIVE" if "mode" in nodes else ""),
                "set": set_count,
                "actual": actual,
                "status": status,
                "updated": last.strftime("%d-%m-%Y %H:%M:%S") if last else None,
            })
        tools.sort(key=lambda t: _tag_key(t["tag"]))
        result[number] = {
            "station": number,
            "vc_number": text(st["vc"], mapped.get("vc_number", "")),
            "mat_number": text(st["mat"], mapped.get("mat_number", "")),
            "tools": tools,
            "status": "idle" if not tools else ("green" if all(t["status"] == "OK" for t in tools) else "red"),
        }
    return result


# ================= OPC UA CLIENT =================

class _Handler:
    def __init__(self, source):
        self.source = source

    def datachange_notification(self, node, val, data):
        self.source._store(node.nodeid, val)

    def status_change_notification(self, status):
        # Server says the subscription/session is gone -> reconnect now, not at the next keepalive.
        logger.warning(f"OPC UA subscription status changed: {status}")
        if self.source._lost is not None:
            self.source._lost.set()


class OpcUaSource:
    """Background OPC UA subscriber. Thread-safe `snapshot()` for the Flask side."""

    def __init__(self, endpoint, node_ids, username=None, password=None, security=None,
                 publishing_interval_ms=1000, retry_seconds=10, keepalive_seconds=15):
        self.endpoint = endpoint
        self.node_ids = sorted(set(node_ids))
        self.username = username
        self.password = password
        self.security = security
        self.publishing_interval_ms = publishing_interval_ms
        self.retry_seconds = retry_seconds
        self.keepalive_seconds = keepalive_seconds

        self._lock = threading.Lock()
        self._values = {}
        self._updated = {}
        self._key_by_nodeid = {}
        self.connected = False
        self.last_error = None
        self._stop = threading.Event()
        self._lost = None  # asyncio.Event, set when the server drops the subscription

    # ---- public ----
    def start(self):
        threading.Thread(target=self._thread_main, name="opcua-source", daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def snapshot(self):
        with self._lock:
            return dict(self._values), dict(self._updated), self.connected

    # ---- internals ----
    def _store(self, nodeid, value):
        key = self._key_by_nodeid.get(nodeid)
        if key is None:
            return
        with self._lock:
            self._values[key] = value
            self._updated[key] = datetime.now()

    def _thread_main(self):
        asyncio.run(self._run_forever())

    async def _run_forever(self):
        while not self._stop.is_set():
            try:
                await self._session()
            except Exception as e:  # network, auth, server restart, ...
                self.last_error = str(e)
                logger.error(f"OPC UA connection to {self.endpoint} failed: {e} - retrying in {self.retry_seconds}s")
            with self._lock:
                self.connected = False
            await asyncio.sleep(self.retry_seconds)

    async def _session(self):
        from asyncua import Client, ua

        client = Client(url=self.endpoint, timeout=10)
        client.session_timeout = 600_000  # 10 min, what most servers grant anyway
        if self.username:
            client.set_user(self.username)
            client.set_password(self.password or "")
        if self.security:
            await client.set_security_string(self.security)

        self._lost = asyncio.Event()
        async with client:
            nodes = []
            for key in self.node_ids:
                nodeid = ua.NodeId.from_string(key)
                self._key_by_nodeid[nodeid] = key
                nodes.append(client.get_node(nodeid))

            sub = await client.create_subscription(self.publishing_interval_ms, _Handler(self))
            results = await sub.subscribe_data_change(
                nodes, sampling_interval=float(self.publishing_interval_ms), queuesize=1)
            bad = [(n, r) for n, r in zip(self.node_ids, results) if isinstance(r, ua.StatusCode)]
            for key, code in bad:
                logger.warning(f"Tag {key} not subscribed: {code}")
            logger.info(f"OPC UA connected to {self.endpoint}: {len(nodes) - len(bad)}/{len(nodes)} tags subscribed")

            with self._lock:
                self.connected = True
                self.last_error = None
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._lost.wait(), timeout=self.keepalive_seconds)
                    raise ConnectionError("subscription lost")
                except asyncio.TimeoutError:
                    pass
                # One tiny read to detect a dead session (server restart / cable pulled).
                await client.nodes.server_state.read_value()
