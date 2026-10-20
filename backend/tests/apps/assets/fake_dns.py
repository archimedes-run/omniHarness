"""A tiny DNS server for the egress tests (#59): answers A queries from
NAMES (name -> list of IPs). A name mapped to "flip:<a>,<b>" alternates
between the two answers on every query, with TTL 0 (DNS rebinding).
Everything else gets NXDOMAIN. Logs every query to stdout."""

import json
import os
import socket
import struct

NAMES = json.loads(os.environ.get("NAMES", "{}"))
counter = {}


def answer(query: bytes) -> bytes:
    tid, flags, qd, _, _, _ = struct.unpack("!HHHHHH", query[:12])
    i, labels = 12, []
    while query[i]:
        n = query[i]
        labels.append(query[i + 1 : i + 1 + n].decode())
        i += n + 1
    qname, qtype = ".".join(labels).lower(), struct.unpack("!H", query[i + 1 : i + 3])[0]
    question = query[12 : i + 5]
    ips = NAMES.get(qname)
    if isinstance(ips, str) and ips.startswith("flip:"):
        a, b = ips[5:].split(",")
        counter[qname] = counter.get(qname, 0) + 1
        ips = [a if counter[qname] % 2 else b]
    print("QUERY", qname, qtype, ips, flush=True)
    if not ips or qtype != 1:
        rcode = 0 if ips else 3
        return struct.pack("!HHHHHH", tid, 0x8180 | rcode, 1, 0, 0, 0) + question
    body = b""
    for ip in ips:
        body += b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + socket.inet_aton(ip)
    return struct.pack("!HHHHHH", tid, 0x8180, 1, len(ips), 0, 0) + question + body


s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", 53))
while True:
    data, addr = s.recvfrom(512)
    try:
        s.sendto(answer(data), addr)
    except Exception as e:  # keep serving
        print("ERROR", e, flush=True)
