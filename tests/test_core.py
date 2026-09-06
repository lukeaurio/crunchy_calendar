import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from crunchy_calendar.core import (
    SeasonalShow,
    current_season,
    current_week_start,
    discover,
    discover_season,
    filter_releases,
    forecast_releases,
    infer_language,
    load_language_config,
    load_watching,
    make_ics,
    parse_calendar,
    parse_monday,
    parse_season_payload,
    previous_week_start,
    validate_season,
)


CALENDAR_HTML = """
<article class="release"><time datetime="2026-08-24T14:00:00+00:00"></time>
<h4><a href="/watch/a">Witch Hat Atelier Season 1</a></h4>
<a href="/watch/a">Episode 10 Available</a></article>
<article class="release"><time datetime="2026-08-24T14:00:00+00:00"></time>
<h4><a href="/watch/b">Witch Hat Atelier Season 1 (English)</a></h4>
<a href="/watch/b">Episode 10 Available</a></article>
<article class="release"><time datetime="2026-08-24T14:00:00+00:00"></time>
<h4><a href="/watch/c">Witch Hat Atelier Season 1 (Deutsch)</a></h4>
<a href="/watch/c">Episode 10 Available</a></article>
"""

SEASON_PAYLOAD = {
    "total": 2,
    "data": [
        {
            "id": "GTEST0001",
            "title": "Witch Hat Atelier",
            "slug_title": "witch-hat-atelier",
            "type": "series",
        },
        {
            "id": "GTEST0002",
            "title": "One Piece",
            "slug_title": "one-piece",
            "type": "series",
        },
    ],
}


class CoreTests(unittest.TestCase):
    def test_dates_and_seasons_are_validated(self):
        self.assertEqual(parse_monday("2026-08-24"), date(2026, 8, 24))
        self.assertEqual(previous_week_start(date(2026, 9, 1)), date(2026, 8, 24))
        self.assertEqual(current_week_start(date(2026, 9, 1)), date(2026, 8, 31))
        self.assertEqual(current_season(date(2026, 9, 1)), "summer-2026")
        self.assertEqual(validate_season("Summer-2026"), "summer-2026")
        with self.assertRaisesRegex(ValueError, "not a Monday"):
            parse_monday("2026-08-25")
        with self.assertRaisesRegex(ValueError, "invalid season"):
            validate_season("monsoon-2026")

    def test_language_inference_uses_japanese_as_the_unsuffixed_default(self):
        self.assertEqual(infer_language("Show"), ("Show", "japanese"))
        self.assertEqual(infer_language("Show (English)"), ("Show", "english"))
        self.assertEqual(infer_language("Show (Deutsch)")[1], "other:Deutsch")
        self.assertEqual(
            infer_language("Show (Português (Brasil))")[1], "other:Português (Brasil)"
        )

    def test_calendar_parser_filters_languages_and_makes_absolute_urls(self):
        releases = parse_calendar(CALENDAR_HTML, {"japanese", "english"})
        self.assertEqual(
            [(item.title, item.language, item.episode) for item in releases],
            [
                ("Witch Hat Atelier Season 1", "japanese", 10),
                ("Witch Hat Atelier Season 1", "english", 10),
            ],
        )
        self.assertTrue(all(item.url.startswith("https://www.crunchyroll.com/watch/") for item in releases))
        self.assertEqual(len(parse_calendar(CALENDAR_HTML + CALENDAR_HTML, {"japanese", "english"})), 2)

    def test_season_payload_maps_only_real_series(self):
        shows, total = parse_season_payload(SEASON_PAYLOAD)
        self.assertEqual(total, 2)
        self.assertEqual(
            shows,
            [
                SeasonalShow("Witch Hat Atelier", "https://www.crunchyroll.com/series/GTEST0001/witch-hat-atelier"),
                SeasonalShow("One Piece", "https://www.crunchyroll.com/series/GTEST0002/one-piece"),
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "invalid total"):
            parse_season_payload({"data": []})

    def test_watchlist_filter_and_ics(self):
        releases = parse_calendar(CALENDAR_HTML, {"japanese", "english"})
        selected = filter_releases(releases, ["Witch Hat Atelier"])
        self.assertEqual(len(selected), 2)
        forecast = forecast_releases(selected, date(2026, 8, 24), date(2026, 8, 31))
        self.assertEqual(forecast[0].episode, 11)
        self.assertEqual(forecast[0].starts_at, "2026-08-31T14:00:00+00:00")
        self.assertEqual(forecast[0].source_starts_at, "2026-08-24T14:00:00+00:00")
        self.assertTrue(forecast[0].predicted)
        calendar = make_ics(forecast)
        self.assertIn("DTSTART:20260831T140000Z", calendar)
        self.assertIn("SUMMARY:Witch Hat Atelier Season 1 - Episode 11", calendar)
        self.assertIn("STATUS:TENTATIVE", calendar)
        self.assertIn("Predicted from the previous week's Crunchyroll release", calendar)
        self.assertTrue(calendar.endswith("END:VCALENDAR\r\n"))

        with self.assertRaisesRegex(ValueError, "immediately follow"):
            forecast_releases(selected, date(2026, 8, 24), date(2026, 9, 7))

    def test_editable_files_are_strictly_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            languages = root / "languages.json"
            languages.write_text(json.dumps({"enabled": ["english"], "patterns": {"english": ["English"]}}))
            self.assertEqual(load_language_config(languages)[0], {"english"})

            watching = root / "watching.json"
            watching.write_text(json.dumps({"shows": [{"title": "One Piece", "aliases": ["ONE PIECE"]}]}))
            self.assertEqual(load_watching(watching), ["one piece", "one piece"])
            watching.write_text(json.dumps({"shows": [{"title": "One Piece", "aliases": "bad"}]}))
            with self.assertRaisesRegex(ValueError, "aliases"):
                load_watching(watching)

    def test_rolling_discovery_tracks_seen_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "discovery.json"
            fetcher = lambda _: CALENDAR_HTML
            first = discover(fetcher, samples=1, days=1, anchor=date(2026, 8, 24), state_path=state)
            second = discover(fetcher, samples=1, days=1, anchor=date(2026, 8, 24), state_path=state)
            self.assertEqual(len(first["new_shows"]), 1)
            self.assertEqual(len(second["seen_shows"]), 1)

    def test_season_discovery_keeps_a_separate_seen_ledger(self):
        shows, _ = parse_season_payload(SEASON_PAYLOAD)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "discovery.json"
            fetcher = lambda _: shows
            first = discover_season("summer-2026", fetcher, state)
            second = discover_season("summer-2026", fetcher, state)
            self.assertEqual(first["show_count"], 2)
            self.assertEqual(len(first["new_shows"]), 2)
            self.assertEqual(len(second["seen_shows"]), 2)


if __name__ == "__main__":
    unittest.main()
