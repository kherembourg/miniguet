#!/usr/bin/env python3
"""Failover relay for the Cloudflare Tunnel: forwards each request to the first Miniguet that answers.

    python3 scripts/failover.py --listen 8767 http://100.75.247.49:8766 http://127.0.0.1:8766

Typical use: the tunnel runs on an always-on Mac and points at this relay. The main Miniguet (on the work Mac, where
most sessions live) is preferred; when it sleeps or is off, the always-on Mac's own Miniguet answers instead.
Headers are passed through untouched (Host, Cf-Access-Jwt-Assertion, cookies...): each Miniguet still checks the
Cloudflare Access token itself. Listens on 127.0.0.1 only. Stdlib only.
"""
import argparse, http.client, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade"}
CHECK_EVERY, CONNECT_TIMEOUT, READ_TIMEOUT = 5, 2, 120
UPSTREAMS, HEALTHY = [], {}


def alive(u):
    try:
        socket.create_connection((u.hostname, u.port or 80), timeout=CONNECT_TIMEOUT).close()
        return True
    except OSError:
        return False


def health_loop():
    last = None
    while True:
        for u in UPSTREAMS:
            HEALTHY[u.geturl()] = alive(u)
        cur = next((u.geturl() for u in UPSTREAMS if HEALTHY[u.geturl()]), None)
        if cur != last:
            print(time.strftime("%H:%M:%S"), "serving from", cur or "nobody", flush=True)
            last = cur
        time.sleep(CHECK_EVERY)


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def relay(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if self.command in ("POST", "PUT") else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        order = sorted(UPSTREAMS, key=lambda u: not HEALTHY.get(u.geturl(), True))   # healthy first, keep preference
        for u in order:
            try:
                c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=CONNECT_TIMEOUT)
                c.connect()
                c.sock.settimeout(READ_TIMEOUT)
                c.request(self.command, self.path, body=body, headers=headers)
                r = c.getresponse()
                data = r.read()
            except OSError:
                HEALTHY[u.geturl()] = False
                continue
            self.send_response_only(r.status, r.reason)
            for k, v in r.getheaders():
                if k.lower() not in HOP and k.lower() != "content-length":
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            c.close()
            return
        self.send_response(502)
        msg = "Miniguet injoignable sur toutes les machines".encode()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    do_GET = do_POST = relay


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=8767)
    ap.add_argument("upstreams", nargs="+", help="Miniguet base URLs, preferred first")
    a = ap.parse_args()
    UPSTREAMS[:] = [urlparse(x) for x in a.upstreams]
    for u in UPSTREAMS:
        HEALTHY[u.geturl()] = True
    threading.Thread(target=health_loop, daemon=True).start()
    print(f"failover relay on http://127.0.0.1:{a.listen} ->", ", ".join(a.upstreams), flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.listen), Relay).serve_forever()
