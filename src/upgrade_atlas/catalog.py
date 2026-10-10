from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit


@dataclass(frozen=True)
class Package:
    name: str
    domains: tuple[str, ...]
    repository: str

    def owns(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.username or parts.password:
                return False
            if parts.port not in (None, 443):
                return False
            for domain in self.domains:
                host, _, path_prefix = domain.partition("/")
                if parts.hostname == host and (
                    not path_prefix
                    or parts.path == "/" + path_prefix
                    or parts.path.startswith("/" + path_prefix + "/")
                ):
                    return True
            if parts.hostname != "github.com":
                return False
            path = unquote(parts.path).lower()
            if any(segment in (".", "..") for segment in path.split("/")):
                return False
            return path == self.repository or path.startswith(self.repository + "/")
        except (ValueError, TypeError):
            return False

    def scope(self, purpose: str) -> str:
        if purpose == "regressions":
            return f"site:github.com{self.repository}/issues"
        return "(" + " OR ".join(f"site:{host}" for host in self.domains) + ")"


PACKAGES = {
    "pydantic": Package(
        "pydantic", ("docs.pydantic.dev", "pydantic.dev/docs/validation"), "/pydantic/pydantic"
    ),
    "numpy": Package("numpy", ("numpy.org",), "/numpy/numpy"),
    "django": Package("django", ("docs.djangoproject.com",), "/django/django"),
    "sqlalchemy": Package("sqlalchemy", ("docs.sqlalchemy.org",), "/sqlalchemy/sqlalchemy"),
}


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    # Search tracking and arbitrary result query parameters do not belong in exports.
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))
