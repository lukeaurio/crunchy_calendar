import unittest
from datetime import date
from html.parser import HTMLParser

from crunchy_calendar.core import (
    fetch_calendar,
    fetch_season_shows,
    forecast_releases,
    parse_calendar,
)
from tests.test_workflows import run_weekly_code


class WorkflowFieldParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {
            "titles": [],
            "source_starts_at": [],
            "urls": [],
            "source_episodes": [],
        }
        self.current = None
        self.depth = 0
        self.capture_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self.current is None and tag == "article" and "release" in classes:
            self.current = {
                "title": "",
                "source_starts_at": "",
                "url": "",
                "source_episode": attributes.get("data-episode-num", ""),
            }
            self.depth = 1
            return
        if self.current is None:
            return
        if tag == "article":
            self.depth += 1
        if self.depth == 1 and tag == "time" and "available-time" in classes:
            self.current["source_starts_at"] = attributes.get("datetime", "")
        if self.depth == 1 and tag == "a" and "js-season-name-link" in classes:
            self.current["url"] = attributes.get("href", "")
        if self.depth == 1 and tag == "cite" and attributes.get("itemprop") == "name":
            self.capture_title = True
            self.title_parts = []

    def handle_data(self, data):
        if self.capture_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if self.capture_title and tag == "cite":
            self.current["title"] = " ".join("".join(self.title_parts).split())
            self.capture_title = False
        if tag == "article":
            self.depth -= 1
            if self.depth == 0:
                self.fields["titles"].append(self.current["title"])
                self.fields["source_starts_at"].append(self.current["source_starts_at"])
                self.fields["urls"].append(self.current["url"])
                self.fields["source_episodes"].append(self.current["source_episode"])
                self.current = None


class LiveCrunchyrollTests(unittest.TestCase):
    """Network tests that prove the real Crunchyroll sources still work."""

    def test_previous_week_page_returns_real_releases(self):
        source_week = date(2026, 8, 24)
        target_week = date(2026, 8, 31)
        html = fetch_calendar(source_week)
        releases = parse_calendar(html, enabled_languages=None)
        self.assertGreater(len(releases), 50)
        self.assertTrue(all(item.title and item.starts_at for item in releases))
        self.assertTrue(all(item.url.startswith("https://www.crunchyroll.com/") for item in releases))
        enabled = parse_calendar(html, enabled_languages={"japanese", "english"})
        self.assertTrue(all(item.language in {"japanese", "english"} for item in enabled))
        self.assertFalse(any("Português" in item.title or "Español" in item.title for item in enabled))
        forecast = forecast_releases(releases, source_week, target_week)
        self.assertEqual(len(forecast), len(releases))
        self.assertTrue(all(item.predicted and item.source_starts_at for item in forecast))
        self.assertTrue(
            all(target_week.isoformat() <= item.starts_at[:10] <= "2026-09-06" for item in forecast)
        )

        fields = WorkflowFieldParser()
        fields.feed(html)
        report = run_weekly_code(
            fields.fields,
            {
                "target_week_start": "2026-08-31",
                "source_week_start": "2026-08-24",
                "watching": ["Mushoku Tensei: Jobless Reincarnation"],
                "languages": {
                    "enabled": ["japanese", "english"],
                    "patterns": {"japanese": ["Japanese", "日本語"], "english": ["English"]},
                },
            },
        )
        self.assertEqual(report["contract_version"], 1)
        self.assertEqual({item["language"] for item in report["releases"]}, {"japanese", "english"})
        self.assertTrue(all(item["predicted"] for item in report["releases"]))

    def test_season_page_source_returns_real_series_without_shell_junk(self):
        shows = fetch_season_shows("summer-2026")
        self.assertGreater(len(shows), 20)
        titles = {show.title.casefold() for show in shows}
        self.assertNotIn("7-day free trial", titles)
        self.assertNotIn("update your web browser!", titles)
        self.assertTrue(all("/series/" in show.url for show in shows))


if __name__ == "__main__":
    unittest.main()
