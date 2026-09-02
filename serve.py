#!/usr/bin/env python3
"""Serve the HDB estate report on 127.0.0.1."""
import argparse, functools, http.server, os, socket, socketserver

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Vendored libraries never change in place, so let the browser keep them.
        # Everything else revalidates: no-cache still allows a 304, unlike no-store,
        # which forced every visitor to re-download ~3 MB on every single page load.
        if self.path.startswith("/vendor/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *a):
        pass  # keep the console quiet


# Stay clear of 8756/8765 and the usual 8000/8080/8888 dev ports.
DEFAULT_PORT = 8642
SCAN = 40


def free_port(preferred):
    for p in [preferred] + list(range(preferred + 1, preferred + SCAN)):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise SystemExit(f"no free port in {preferred}-{preferred + SCAN}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    args = ap.parse_args()
    port = free_port(args.port)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(
            ("127.0.0.1", port), functools.partial(Handler, directory=SITE)) as httpd:
        print(f"HDB estate report  ->  http://127.0.0.1:{port}/", flush=True)
        print("Ctrl-C to stop.", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
