import json
from datetime import UTC, datetime

import pytest

from upgrade_atlas.catalog import PACKAGES, canonical_url
from upgrade_atlas.cli import main
from upgrade_atlas.example import example_report
from upgrade_atlas.provider import ProviderError, SerpApi
from upgrade_atlas.research import (
    markdown_report,
    mentions_version,
    research_upgrade,
    validate_request,
)

PAIR = {"package": "numpy", "current": "1.26.4", "target": "2.0.0"}


def response(rows=None, **extra):
    return {
        "search_metadata": {"status": "Success", "id": "provider-search-1"},
        "organic_results": rows if rows is not None else [],
        **extra,
    }


def row(url="https://numpy.org/doc/stable/release/2.0.0-notes.html", **extra):
    return {"title": "NumPy 2.0.0 release", "link": url, "snippet": "A search excerpt.", **extra}


@pytest.mark.parametrize(
    "url",
    [
        "https://numpy.org/doc/stable/release.html",
        "https://github.com/numpy/numpy/issues/1",
        "https://github.com/NumPy/NumPy/releases",
    ],
)
def test_primary_source_acceptance(url):
    assert PACKAGES["numpy"].owns(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://numpy.org.evil.example/doc",
        "http://numpy.org/doc",
        "https://evil.example/numpy.org",
        "https://numpy.org@evil.example/doc",
        "https://a:numpy.org@numpy.org/doc",
        "https://numpy.org:8080/doc",
        "https://github.com/numpy/numpy-evil/issues/1",
        "https://github.com/random/numpy/issues/1",
        "https://github.com/numpy/numpy/../random",
        "https://github.com/numpy/numpy/%2e%2e/random",
        "javascript:alert(1)",
        "https://[invalid",
    ],
)
def test_source_spoofing_rejected(url):
    assert not PACKAGES["numpy"].owns(url)


def test_new_pydantic_domain_is_scoped_to_validation():
    package = PACKAGES["pydantic"]
    assert package.owns("https://pydantic.dev/docs/validation/latest/get-started/migration/")
    assert not package.owns("https://pydantic.dev/docs/ai/some-different-package")


def test_url_tracking_is_removed():
    assert canonical_url("https://numpy.org/path?api_key=secret&utm_source=x#fragment") == (
        "https://numpy.org/path"
    )


@pytest.mark.parametrize(
    "data",
    [
        {},
        [],
        {**PAIR, "extra": "value"},
        {**PAIR, "package": "numpy site:evil.example"},
        {**PAIR, "current": "2.0.0"},
        {**PAIR, "target": "1.0.0"},
        {**PAIR, "target": ">=2.0"},
        {**PAIR, "target": "2.0\nsite:evil.example"},
        {**PAIR, "target": "latest"},
        {**PAIR, "target": "2" * 100},
        {**PAIR, "current": None},
    ],
)
def test_invalid_upgrade_requests(data):
    with pytest.raises(ValueError):
        validate_request(data)


@pytest.mark.parametrize("text", ["2.0.0", "v2.0.0 release", "NumPy 2.0.0."])
def test_exact_version_match(text):
    assert mentions_version(text, "2.0.0")


@pytest.mark.parametrize("text", ["12.0.0", "2.0.0.1", "2.0.0rc1", "2.0.01"])
def test_version_prefix_is_not_exact(text):
    assert not mentions_version(text, "2.0.0")


def test_provider_cache_and_budget():
    calls = []
    client = SerpApi(
        "test-key", call=lambda params: calls.append(params) or response(), max_calls=1
    )
    assert client.search("query")["local_cache"] is False
    assert client.search("query")["local_cache"] is True
    with pytest.raises(ProviderError, match="Local search budget"):
        client.search("different query")
    assert len(calls) == client.calls == 1
    assert calls[0]["engine"] == "google"


def test_provider_secrets_and_request_metadata_are_not_exported():
    client = SerpApi(
        "private-test-value",
        call=lambda _: response(
            [row(snippet="private-test-value")],
            search_parameters={"api_key": "private-test-value"},
        ),
    )
    result = client.search("query")
    assert "private-test-value" not in json.dumps(result)
    assert "search_parameters" not in result


@pytest.mark.parametrize(
    "body",
    [
        {"error": "private-test-value"},
        {"search_metadata": {"status": "Processing", "id": "x"}},
        {"search_metadata": {"status": "Success"}},
        response("malformed"),
        [],
    ],
)
def test_bad_provider_response_does_not_become_success(body):
    client = SerpApi("private-test-value", call=lambda _: body)
    with pytest.raises(ProviderError) as caught:
        client.search("query")
    assert "private-test-value" not in str(caught.value)


def test_raw_provider_exception_is_sanitized():
    def fail(_):
        raise RuntimeError("request URL includes private-test-value")

    with pytest.raises(ProviderError) as caught:
        SerpApi("private-test-value", call=fail).search("query")
    assert "private-test-value" not in str(caught.value)


def test_missing_key_does_not_make_request():
    with pytest.raises(ProviderError, match="Set SERPAPI_API_KEY"):
        SerpApi("")


def test_source_deduplication_preserves_all_search_provenance():
    count = 0

    def search(_):
        nonlocal count
        count += 1
        return {"search_id": str(count), "organic_results": [row()]}

    report = research_upgrade(PAIR, search, now=lambda: datetime(2026, 10, 10, tzinfo=UTC))
    assert len(report["sources"]) == 1
    assert report["sources"][0]["search_ids"] == ["1", "2", "3"]
    assert len(report["sources"][0]["observations"]) == 3
    assert len(report["searches"]) == 3
    assert report["verdict"] == "REVIEW REQUIRED"
    assert report["retrieved_at"].startswith("2026-10-10")


def test_target_match_does_not_leak_between_purposes():
    count = 0

    def search(_):
        nonlocal count
        count += 1
        return {
            "search_id": str(count),
            "organic_results": [
                row(
                    "https://numpy.org/doc/",
                    title=("NumPy 2.0.0" if count == 1 else "NumPy unrelated"),
                )
            ],
        }

    report = research_upgrade(PAIR, search)
    assert report["coverage"][0]["source_ids"] == ["S1"]
    assert report["coverage"][1]["source_ids"] == []
    assert report["coverage"][2]["source_ids"] == []


def test_partial_provider_failure_retains_evidence():
    def search(query):
        if "migration" in query:
            raise ProviderError("Provider quota reached.")
        return {"search_id": "successful-id", "organic_results": [row()]}

    report = research_upgrade(PAIR, search)
    assert len(report["sources"]) == 1
    assert report["searches"][1]["state"] == "error"
    assert report["coverage"][1]["source_ids"] == []
    assert report["review_gaps"]


def test_nonprimary_and_malformed_rows_are_counted_as_excluded():
    report = research_upgrade(
        PAIR,
        lambda _: {
            "search_id": "id",
            "organic_results": [row("https://example.org/"), {}, "invalid"],
        },
    )
    assert not report["sources"]
    assert all(item["excluded"] == 3 for item in report["searches"])
    assert all(not item["source_ids"] for item in report["coverage"])


def test_synthetic_example_is_always_identified():
    report = example_report()
    assert report["mode"] == "synthetic_example"
    assert all("SYNTHETIC" in item["search_id"] for item in report["searches"])
    assert "synthetic_example" in markdown_report(report)
    assert not report["coverage"][-1]["source_ids"]


def test_markdown_does_not_turn_source_instructions_into_markup():
    report = research_upgrade(
        PAIR,
        lambda _: {
            "search_id": "id",
            "organic_results": [row(snippet="<script>alert(1)</script> [do](evil)")],
        },
    )
    result = markdown_report(report)
    assert "\\<script\\>" in result
    assert "\\[do\\]" in result
    assert "Search snippets are not inspected full documents" in result


def test_cli_example_is_no_key_and_explicit(capsys, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    assert main(["example", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "synthetic_example"


def test_cli_live_without_key_fails(capsys, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    assert main(["research", "numpy", "1.26.4", "2.0.0"]) == 2
    assert "Set SERPAPI_API_KEY" in capsys.readouterr().err
