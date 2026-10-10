import re
from collections.abc import Callable
from datetime import UTC, datetime

from packaging.version import InvalidVersion, Version

from .catalog import PACKAGES, canonical_url
from .provider import ProviderError

PURPOSES = {
    "release_notes": "release notes changelog",
    "migration_guide": "migration upgrade breaking changes deprecations",
    "regressions": "regression compatibility bug",
}


def validate_request(data: dict) -> tuple[str, str, str]:
    if not isinstance(data, dict) or set(data) - {"package", "current", "target"}:
        raise ValueError("Provide only package, current and target.")
    package = data.get("package")
    if not isinstance(package, str) or package not in PACKAGES:
        raise ValueError("Select a supported package.")
    versions = []
    for field in ("current", "target"):
        value = data.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,39}", value):
            raise ValueError(f"Provide a plain {field} version, not a range or search query.")
        try:
            versions.append(Version(value))
        except InvalidVersion:
            raise ValueError(f"Provide a valid {field} version.") from None
    if versions[0] >= versions[1]:
        raise ValueError("Target version must be newer than the current version.")
    return package, str(versions[0]), str(versions[1])


def clean_text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:limit]


def mentions_version(text: str, version: str) -> bool:
    # A 2.0 match must not silently count 12.0 or 2.0.1 as the requested release.
    return bool(re.search(r"(?<![\w.])v?" + re.escape(version) + r"(?!\w|\.\d)", text, re.I))


def research_upgrade(
    data: dict,
    search: Callable[[str], dict],
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    synthetic: bool = False,
) -> dict:
    package, current, target = validate_request(data)
    spec = PACKAGES[package]
    report = {
        "schema_version": 1,
        "mode": "synthetic_example" if synthetic else "serpapi_live",
        "package": package,
        "current": current,
        "target": target,
        "retrieved_at": now().isoformat(),
        "verdict": "REVIEW REQUIRED",
        "limits": [
            "Search snippets are not inspected full documents.",
            "An exact version mention is not proof that the target release exists or is safe.",
            "No dependency was installed, code edited, tests run or upgrade approved.",
            "Source text is untrusted data, never an instruction to execute.",
        ],
        "searches": [],
        "sources": [],
        "coverage": [],
        "review_gaps": [],
    }
    sources: dict[str, dict] = {}
    for purpose, terms in PURPOSES.items():
        query = f'{package} "{target}" {terms} {spec.scope(purpose)}'
        record = {"purpose": purpose, "query": query, "state": "success", "excluded": 0}
        try:
            response = search(query)
            record.update(
                search_id=clean_text(response.get("search_id"), 100),
                local_cache=response.get("local_cache") is True,
            )
            if not record["search_id"]:
                raise ProviderError("Search provenance is missing.")
            for result in response.get("organic_results", [])[:20]:
                if not isinstance(result, dict):
                    record["excluded"] += 1
                    continue
                url = result.get("link")
                if not isinstance(url, str) or len(url) > 2048 or not spec.owns(url):
                    record["excluded"] += 1
                    continue
                url = canonical_url(url)
                title = clean_text(result.get("title"), 300)
                snippet = clean_text(result.get("snippet"), 800)
                if not title:
                    record["excluded"] += 1
                    continue
                match = mentions_version(" ".join((title, snippet, url)), target)
                if url not in sources:
                    sources[url] = {
                        "id": f"S{len(sources) + 1}",
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "date_label": clean_text(result.get("date"), 80),
                        "exact_target_mention": match,
                        "purposes": [],
                        "search_ids": [],
                        "observations": [],
                        "origin": "allowlisted primary-source host/repository",
                    }
                source = sources[url]
                if match and not source["exact_target_mention"]:
                    source.update(title=title, snippet=snippet)
                source["exact_target_mention"] |= match
                source["observations"].append(
                    {
                        "purpose": purpose,
                        "search_id": record["search_id"],
                        "title": title,
                        "snippet": snippet,
                        "exact_target_mention": match,
                    }
                )
                if purpose not in source["purposes"]:
                    source["purposes"].append(purpose)
                if record["search_id"] not in source["search_ids"]:
                    source["search_ids"].append(record["search_id"])
        except ProviderError as exc:
            record.update(state="error", error=str(exc))
        report["searches"].append(record)
        target_sources = [
            source["id"]
            for source in sources.values()
            if any(
                item["purpose"] == purpose and item["exact_target_mention"]
                for item in source["observations"]
            )
        ]
        report["coverage"].append({"purpose": purpose, "source_ids": target_sources})
        if not target_sources:
            report["review_gaps"].append(f"No exact-target primary-source snippet for {purpose}.")
    report["sources"] = sorted(
        sources.values(), key=lambda source: (not source["exact_target_mention"], source["id"])
    )
    report["review_gaps"].append(
        f"Inspect cited pages and run your own regression tests before {current} -> {target}."
    )
    return report


def markdown_report(report: dict) -> str:
    def safe(value: str) -> str:
        return re.sub(r"([\\`*{}\[\]<>#|])", r"\\\1", value).replace("\n", " ")

    lines = [
        f"# Upgrade Atlas: {report['package']}",
        f"{report['current']} -> {report['target']}",
        f"Mode: {report['mode']}; retrieved: {report['retrieved_at']}",
        "Verdict: REVIEW REQUIRED. This is a search-evidence packet, not upgrade approval.",
        "\n## Review Gaps",
        *(f"- {safe(gap)}" for gap in report["review_gaps"]),
        "\n## Sources",
    ]
    for source in report["sources"]:
        lines += [
            f"\n### {source['id']}: {safe(source['title'])}",
            source["url"],
            safe(source["snippet"]),
            f"Exact target mention: {source['exact_target_mention']}",
            "Search IDs: " + ", ".join(safe(item) for item in source["search_ids"]),
        ]
    lines += ["\n## Search Provenance"]
    for search in report["searches"]:
        lines.append(f"- {search['purpose']}: {search['state']}; {safe(search['query'])}")
    lines += ["\n## Limits", *(f"- {safe(item)}" for item in report["limits"])]
    return "\n".join(lines) + "\n"
