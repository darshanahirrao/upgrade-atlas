import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

from .catalog import PACKAGES
from .example import example_report
from .provider import ProviderError, SerpApi
from .research import markdown_report, research_upgrade

MAX_BODY = 4096
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript")}
ASSETS["/style.css"] = ("style.css", "text/css")


def handler_factory(client: SerpApi | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, code: int, content: bytes, content_type="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

        def json_response(self, code: int, body: dict):
            self.respond(code, json.dumps(body).encode())

        def trusted_request(self) -> bool:
            host = self.headers.get("Host", "")
            port = self.server.server_port
            if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in (
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            )

        def do_GET(self):
            if not self.trusted_request():
                self.json_response(403, {"error": "Untrusted host or origin."})
            elif self.path in ASSETS:
                filename, content_type = ASSETS[self.path]
                self.respond(
                    200, files("upgrade_atlas").joinpath("web", filename).read_bytes(), content_type
                )
            elif self.path == "/api/status":
                self.json_response(
                    200,
                    {
                        "live_ready": client is not None,
                        "packages": list(PACKAGES),
                        "local_calls": client.calls if client else 0,
                        "local_budget": 12,
                    },
                )
            elif self.path == "/api/example":
                report = example_report()
                self.json_response(200, {"report": report, "markdown": markdown_report(report)})
            else:
                self.json_response(404, {"error": "Not found."})

        def do_POST(self):
            if not self.trusted_request():
                self.json_response(403, {"error": "Untrusted host or origin."})
                return
            if self.path != "/api/research":
                self.json_response(404, {"error": "Not found."})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.json_response(415, {"error": "Send JSON."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY:
                    self.json_response(413, {"error": "Request exceeds the local body limit."})
                    return
                self.connection.settimeout(5)
                data = json.loads(self.rfile.read(length))
                if client is None:
                    raise ProviderError("Live research is unavailable until the server key is set.")
                report = research_upgrade(data, client.search)
                self.json_response(200, {"report": report, "markdown": markdown_report(report)})
            except ProviderError as exc:
                self.json_response(503, {"error": str(exc)})
            except (ValueError, UnicodeError):
                self.json_response(
                    400, {"error": "Provide a supported package and valid upgrade pair."}
                )
            except (TimeoutError, OSError):
                self.json_response(408, {"error": "Request body did not complete."})

    return Handler


def serve(port: int):
    key = os.environ.get("SERPAPI_API_KEY", "")
    client = SerpApi(key) if key.strip() else None
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_factory(client))
    print(f"Upgrade Atlas: http://127.0.0.1:{port}, live ready: {client is not None}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
