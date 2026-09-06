import unittest
from datetime import date

from crunchy_calendar.core import (
    fetch_calendar,
    fetch_season_shows,
    forecast_releases,
    parse_calendar,
)


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

    def test_season_page_source_returns_real_series_without_shell_junk(self):
        shows = fetch_season_shows("summer-2026")
        self.assertGreater(len(shows), 20)
        titles = {show.title.casefold() for show in shows}
        self.assertNotIn("7-day free trial", titles)
        self.assertNotIn("update your web browser!", titles)
        self.assertTrue(all("/series/" in show.url for show in shows))


if __name__ == "__main__":
    unittest.main()
