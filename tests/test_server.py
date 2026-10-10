import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from upgrade_atlas.provider import SerpApi
from upgrade_atlas.server import handler_factory


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(None))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def request(server, method="GET", path="/", body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    connection.request(method, path, body, headers or {})
    response = connection.getresponse()
    data = response.read()
    status, response_headers = response.status, dict(response.getheaders())
    connection.close()
    return status, response_headers, data


def test_static_assets_and_security_headers(server):
    for path in ("/", "/style.css", "/app.js"):
        status, headers, body = request(server, path=path)
        assert status == 200 and body
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
        assert "no-store" == headers["Cache-Control"]


def test_status_is_truthful_and_has_no_key(server):
    status, _, body = request(server, path="/api/status")
    assert status == 200
    assert json.loads(body)["live_ready"] is False
    assert "api_key" not in body.decode()


def test_example_is_not_live_evidence(server):
    status, _, body = request(server, path="/api/example")
    assert status == 200
    assert json.loads(body)["report"]["mode"] == "synthetic_example"


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Origin": "https://evil.example"}])
def test_dns_rebinding_and_cross_origin_requests_blocked(server, headers):
    status, _, _ = request(server, headers=headers)
    assert status == 403


def test_missing_live_key_fails_without_synthetic_fallback(server):
    status, _, body = request(
        server, "POST", "/api/research", "{}", {"Content-Type": "application/json"}
    )
    assert status == 503
    assert "Live research is unavailable" in json.loads(body)["error"]


@pytest.mark.parametrize("body", ["{bad-json", "", "x" * 4097])
def test_invalid_and_oversized_bodies(server, body):
    status, _, _ = request(
        server, "POST", "/api/research", body, {"Content-Type": "application/json"}
    )
    assert status in (400, 413)


def test_content_type_rejected(server):
    assert request(server, "POST", "/api/research", "{}")[0] == 415


def test_missing_routes_do_not_leak_files(server):
    for path in ("/../../.env", "/.env", "/api/research?api_key=x"):
        assert request(server, path=path)[0] == 404


def test_live_path_with_mock_provider_is_explicit_test_only():
    client = SerpApi(
        "private-test-key",
        call=lambda _: {
            "search_metadata": {"status": "Success", "id": "mock-search-id"},
            "organic_results": [],
        },
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(client))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"package": "numpy", "current": "1.26.4", "target": "2.0.0"})
        status, _, result = request(
            httpd, "POST", "/api/research", body, {"Content-Type": "application/json"}
        )
        assert status == 200
        assert client.calls == 3
        assert "private-test-key" not in result.decode()
        assert json.loads(result)["report"]["verdict"] == "REVIEW REQUIRED"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
