"""Invented search responses for UI/testing only, never evidence of a live API call."""

from .research import research_upgrade


def example_report() -> dict:
    def search(query: str) -> dict:
        if "regression" in query:
            return {
                "search_id": "SYNTHETIC-regressions",
                "organic_results": [
                    {
                        "title": "Synthetic third-party report for NumPy 2.0.0",
                        "link": "https://example.org/not-an-official-source",
                        "snippet": "Invented row: deliberately excluded by the source policy.",
                    }
                ],
            }
        migration = "migration" in query
        return {
            "search_id": "SYNTHETIC-migration" if migration else "SYNTHETIC-release",
            "organic_results": [
                {
                    "title": "Synthetic NumPy 2.0.0 migration result"
                    if migration
                    else "Synthetic NumPy 2.0.0 release result",
                    "link": "https://numpy.org/doc/stable/numpy_2_0_migration_guide.html"
                    if migration
                    else "https://numpy.org/doc/stable/release/2.0.0-notes.html",
                    "snippet": "Invented NumPy 2.0.0 excerpt for testing the evidence ledger. "
                    "This is not retrieved documentation or a compatibility finding.",
                }
            ],
        }

    return research_upgrade(
        {"package": "numpy", "current": "1.26.4", "target": "2.0.0"}, search, synthetic=True
    )
