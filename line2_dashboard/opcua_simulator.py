"""
Stand-in OPC UA server for trying `source = opcua` without the real SCADA.

Serves every node_id in a tag map (default tag_map.csv.example) and slowly
counts the Actual Count tags up, so boxes turn from red to green.

    python opcua_simulator.py                 # opc.tcp://127.0.0.1:4840
    python opcua_simulator.py --tag-map tag_map.csv --port 4841
"""
import argparse
import asyncio
import os
import random

from opcua_source import load_tag_map


async def main(args):
    from asyncua import Server

    rows = load_tag_map(args.tag_map)
    server = Server()
    await server.init()
    server.set_endpoint(f"opc.tcp://0.0.0.0:{args.port}/")
    idx = await server.register_namespace("urn:line2:simulator")
    folder = await server.nodes.objects.add_folder(idx, "Line2Simulator")

    nodes = {}
    for r in rows:
        initial = {"vc": "55072654300R", "mat": f"MAT784062TFJ127{80 + r['station']:02d}",
                   "set": 5, "actual": random.randint(0, 5), "status": False, "mode": False}[r["kind"]]
        # the node ids in the tag map point at namespace 2 - keep whatever they say
        var = await folder.add_variable(r["node_id"], r["node_id"].split("=")[-1], initial)
        nodes[r["node_id"]] = (r, var)

    print(f"Simulating {len(nodes)} tags on opc.tcp://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    async with server:
        while True:
            await asyncio.sleep(args.step)
            for r, var in nodes.values():
                if r["kind"] == "actual":
                    value = await var.read_value()
                    await var.write_value(0 if value >= 5 else value + 1)
            actuals = {(r["station"], r["tool"]): await var.read_value()
                       for r, var in nodes.values() if r["kind"] == "actual"}
            for r, var in nodes.values():
                if r["kind"] == "status":
                    await var.write_value(actuals.get((r["station"], r["tool"]), 0) >= 5)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tag-map", default=os.path.join(os.path.dirname(__file__), "tag_map.csv.example"))
    p.add_argument("--port", type=int, default=4840)
    p.add_argument("--step", type=float, default=3.0, help="seconds between count changes")
    asyncio.run(main(p.parse_args()))
