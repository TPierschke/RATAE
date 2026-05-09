#!/usr/bin/env python3
"""
Diagnose-UDP-Listener fuer CoE auf Port 5441.
Loggt jedes eingehende Paket: Timestamp, Source-IP, Laenge, Hex-Dump.
"""
import socket
from datetime import datetime

PORT = 5441
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", PORT))

print(f"Listening on UDP/{PORT}...", flush=True)
n = 0
while True:
    try:
        data, addr = sock.recvfrom(2048)
    except KeyboardInterrupt:
        break
    n += 1
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    hex_dump = data.hex()
    print(f"#{n:04d} {ts} from={addr[0]:15s} len={len(data):3d}  hex={hex_dump}", flush=True)
