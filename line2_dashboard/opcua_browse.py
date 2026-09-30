"""
List the tags a SCADA exposes over OPC UA, to help fill in tag_map.csv.

Read-only and run once by hand (not by the dashboard). Walks the address space
from a start node and prints one CSV line per variable:  node_id,path,value

    python opcua_browse.py opc.tcp://<scada-ip>:4840
    python opcua_browse.py opc.tcp://<scada-ip>:4840 --start "ns=2;s=Line2" --depth 4 > tags.csv
    python opcua_browse.py opc.tcp://<scada-ip>:4840 --user admin --password secret

Keep --start as narrow as possible on a big SCADA; --max-nodes stops the walk early.
"""
import argparse
import asyncio
import csv
import sys


async def browse(args):
    from asyncua import Client, ua

    client = Client(url=args.endpoint, timeout=10)
    if args.user:
        client.set_user(args.user)
        client.set_password(args.password or "")
    if args.security:
        await client.set_security_string(args.security)

    out = csv.writer(sys.stdout)
    out.writerow(["node_id", "path", "value"])
    seen = 0
    async with client:
        start = client.get_node(args.start) if args.start else client.nodes.objects
        stack = [(start, "", 0)]
        while stack and seen < args.max_nodes:
            node, path, depth = stack.pop()
            for child in await node.get_children():
                seen += 1
                name = (await child.read_browse_name()).Name
                child_path = f"{path}/{name}" if path else name
                node_class = await child.read_node_class()
                if node_class == ua.NodeClass.Variable:
                    try:
                        value = await child.read_value()
                    except Exception as e:
                        value = f"<{type(e).__name__}>"
                    out.writerow([child.nodeid.to_string(), child_path, value])
                elif node_class == ua.NodeClass.Object and depth + 1 < args.depth and name != "Server":
                    stack.append((child, child_path, depth + 1))
                if seen >= args.max_nodes:
                    print(f"# stopped after {args.max_nodes} nodes; narrow --start", file=sys.stderr)
                    break


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("endpoint")
    p.add_argument("--start", help='node id to start from, e.g. "ns=2;s=Line2" (default: Objects)')
    p.add_argument("--depth", type=int, default=5)
    p.add_argument("--max-nodes", type=int, default=5000)
    p.add_argument("--user")
    p.add_argument("--password")
    p.add_argument("--security", help='e.g. "Basic256Sha256,SignAndEncrypt,cert.der,key.pem"')
    asyncio.run(browse(p.parse_args()))


if __name__ == "__main__":
    main()
