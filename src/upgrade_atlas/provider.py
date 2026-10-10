import json
import threading
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE = 1024 * 1024


class ProviderError(Exception):
    """A sanitized error that cannot contain a key or a request URL."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(params: dict) -> dict:
    request = Request(
        "https://serpapi.com/search.json?" + urlencode(params),
        headers={"Accept": "application/json", "User-Agent": "UpgradeAtlas/0.1"},
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=25) as response:
            body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ProviderError("Provider response exceeded the local size limit.")
        result = json.loads(body)
        if not isinstance(result, dict):
            raise ProviderError("Provider response was not a JSON object.")
        return result
    except HTTPError as exc:
        if exc.code == 429:
            raise ProviderError(
                "Provider quota or rate limit reached. No retry or top-up."
            ) from None
        if exc.code in (401, 403):
            raise ProviderError("Provider rejected the API key or account access.") from None
        raise ProviderError(f"Provider returned HTTP {exc.code}. No redirect or retry.") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProviderError("Provider request failed. No automatic retry was made.") from None


class SerpApi:
    def __init__(self, key: str, *, call: Callable[[dict], dict] = transport, max_calls: int = 12):
        if not isinstance(key, str) or not key.strip():
            raise ProviderError("Set SERPAPI_API_KEY on the server before live research.")
        self._key = key.strip()
        self._call = call
        self._max_calls = max_calls
        self._calls = 0
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        return self._calls

    def search(self, query: str) -> dict:
        # Serialize cache/budget checks so simultaneous requests cannot overspend this process.
        with self._lock:
            if query in self._cache:
                return {**self._cache[query], "local_cache": True}
            if self._calls >= self._max_calls:
                raise ProviderError(
                    "Local search budget reached. Restart only after checking quota."
                )
            self._calls += 1
            try:
                response = self._call(
                    {"engine": "google", "q": query, "hl": "en", "api_key": self._key}
                )
                if not isinstance(response, dict):
                    raise ProviderError("Provider returned an invalid response.")
                metadata = response.get("search_metadata")
                if response.get("error") or not isinstance(metadata, dict):
                    raise ProviderError("Provider search failed or lacked provenance.")
                if metadata.get("status") != "Success" or not metadata.get("id"):
                    raise ProviderError("Provider search was not confirmed successful.")
                # Export only the fields needed for evidence; never export provider request URLs.
                minimal = {
                    "search_id": str(metadata["id"])[:100],
                    "organic_results": response.get("organic_results", []),
                    "local_cache": False,
                }
                safe = json.loads(json.dumps(minimal).replace(self._key, "[redacted]"))
                if not isinstance(safe["organic_results"], list):
                    raise ProviderError("Provider organic results were malformed.")
                self._cache[query] = safe
                return safe
            except ProviderError:
                raise
            except Exception:
                raise ProviderError(
                    "Provider request failed. No raw error or key was exported."
                ) from None
