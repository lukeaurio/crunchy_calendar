from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://www.crunchyroll.com"
CALENDAR_URL = f"{BASE_URL}/simulcastcalendar"
AUTH_URL = f"{BASE_URL}/auth/v1/token"
SEASONAL_URL = f"{BASE_URL}/content/v2/discover/browse"
SEASONS = {"spring", "summer", "fall", "winter"}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# Crunchyroll ships this public anonymous web-client credential in its website.
# It is not a user credential and grants no account access.
PUBLIC_WEB_AUTH = "Basic dC1rZGdwMmg4YzNqdWI4Zm4wZnE6eWZMRGZNZnJZdktYaDRKWFMxTEVJMmNDcXUxdjVXYW4="
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
DEFAULT_LANGUAGE_CONFIG = {
    "enabled": ["japanese", "english"],
    "patterns": {"japanese": ["Japanese", "日本語"], "english": ["English"]},
}


@dataclass(frozen=True)
class Release:
    title: str
    language: str
    episode: int | None
    starts_at: str
    url: str


@dataclass(frozen=True)
class SeasonalShow:
    title: str
    url: str


def _validate_timeout(timeout: float) -> float:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ValueError("timeout must be a number")
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    return timeout


def _request_bytes(request: Request, timeout: float, label: str) -> bytes:
    timeout = _validate_timeout(timeout)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise RuntimeError(f"{label} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"could not fetch {label}: {reason}") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError(f"{label} response exceeds 8 MiB safety limit")
    return body


def _request_json(request: Request, timeout: float, label: str) -> dict:
    body = _request_bytes(request, timeout, label)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned a non-object JSON response")
    return payload


def parse_monday(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid date {value!r}; expected YYYY-MM-DD") from exc
    if parsed.weekday() != 0:
        raise ValueError(f"date {value} is not a Monday")
    return parsed


def previous_week_start(today: date | None = None) -> date:
    today = today or date.today()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7)


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    if not isinstance(today, date):
        raise ValueError("today must be a date")
    name = ("winter", "spring", "summer", "fall")[(today.month - 1) // 3]
    return f"{name}-{today.year}"


def validate_season(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("season must be a string")
    match = re.fullmatch(r"(spring|summer|fall|winter)-(\d{4})", value.lower().strip())
    if not match:
        raise ValueError(
            f"invalid season {value!r}; expected spring, summer, fall, or winter followed by a year"
        )
    return f"{match.group(1)}-{match.group(2)}"


def fetch_calendar(week_start: date, timeout: float = 30.0) -> str:
    if not isinstance(week_start, date) or week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday date")
    query = urlencode({"filter": "premium", "date": week_start.isoformat()})
    request = Request(
        f"{CALENDAR_URL}?{query}",
        headers={**HTTP_HEADERS, "Accept": "text/html,application/xhtml+xml"},
    )
    return _request_bytes(request, timeout, "Crunchyroll calendar").decode("utf-8", errors="replace")


def _anonymous_token(timeout: float) -> str:
    device_id = str(uuid.uuid4())
    body = urlencode(
        {
            "grant_type": "client_id",
            "scope": "offline_access",
            "device_id": device_id,
            "device_type": "com.crunchyroll.web",
        }
    ).encode()
    request = Request(
        AUTH_URL,
        data=body,
        headers={
            **HTTP_HEADERS,
            "Accept": "application/json",
            "Authorization": PUBLIC_WEB_AUTH,
            "Content-Type": "application/x-www-form-urlencoded",
            "ETP-Anonymous-ID": device_id,
        },
    )
    payload = _request_json(request, timeout, "Crunchyroll anonymous authentication")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Crunchyroll anonymous authentication returned no access token")
    return token


def _season_page(season: str, token: str, start: int, timeout: float) -> dict:
    query = urlencode({"seasonal_tag": season, "locale": "en-US", "n": 100, "start": start})
    request = Request(
        f"{SEASONAL_URL}?{query}",
        headers={
            **HTTP_HEADERS,
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/simulcasts/seasons/{season}",
        },
    )
    return _request_json(request, timeout, f"Crunchyroll seasonal catalog for {season}")


def parse_season_payload(payload: dict) -> tuple[list[SeasonalShow], int]:
    if not isinstance(payload, dict):
        raise RuntimeError("seasonal catalog must be a JSON object")
    total = payload.get("total")
    items = payload.get("data")
    if not isinstance(total, int) or total < 0 or not isinstance(items, list):
        raise RuntimeError("seasonal catalog has an invalid total or data list")

    shows: list[SeasonalShow] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "series":
            raise RuntimeError("seasonal catalog contains a non-series item")
        series_id = item.get("id")
        title = item.get("title")
        slug = item.get("slug_title")
        if not all(isinstance(value, str) and value.strip() for value in (series_id, title, slug)):
            raise RuntimeError("seasonal catalog contains a series with missing identity fields")
        shows.append(
            SeasonalShow(
                title=" ".join(title.split()),
                url=f"{BASE_URL}/series/{series_id}/{slug}",
            )
        )
    return shows, total


def fetch_season_shows(season: str, timeout: float = 30.0) -> list[SeasonalShow]:
    season = validate_season(season)
    timeout = _validate_timeout(timeout)
    token = _anonymous_token(timeout)
    shows: list[SeasonalShow] = []
    start = 0
    total: int | None = None

    while total is None or start < total:
        page, page_total = parse_season_payload(_season_page(season, token, start, timeout))
        total = page_total
        if not page and start < total:
            raise RuntimeError(f"seasonal catalog for {season} stopped before all shows were returned")
        shows.extend(page)
        start += len(page)

    unique = list({show.url: show for show in shows}.values())
    if not unique:
        raise RuntimeError(f"seasonal catalog for {season} contained no series")
    return unique


def infer_language(
    title: str, patterns: dict[str, list[str]] | None = None
) -> tuple[str, str]:
    patterns = patterns or DEFAULT_LANGUAGE_CONFIG["patterns"]
    clean = " ".join(unescape(title).split()).strip()
    match = re.search(r"\s+\(([^()]*)\)\s*$", clean)
    if match:
        suffix = match.group(1).casefold()
        for language, values in patterns.items():
            if any(suffix == value.casefold() for value in values):
                return clean[: match.start()].strip(), language
        return clean, f"other:{match.group(1)}"
    # Crunchyroll leaves the original Japanese audio entry unsuffixed.
    return clean, "japanese"


class _CalendarParser(HTMLParser):
    def __init__(
        self,
        enabled_languages: set[str] | None = None,
        patterns: dict[str, list[str]] | None = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.releases: list[Release] = []
        self.enabled_languages = enabled_languages
        self.patterns = patterns or DEFAULT_LANGUAGE_CONFIG["patterns"]
        self.article: dict[str, str] | None = None
        self.article_depth = 0
        self.capture: str | None = None
        self.buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = set((attr.get("class") or "").split())
        if tag == "article" and "release" in classes:
            self.article = {"url": "", "title": "", "episode": "", "starts_at": ""}
            self.article_depth = 1
        elif self.article is not None:
            if tag == "article":
                self.article_depth += 1
            if tag == "time" and attr.get("datetime"):
                self.article["starts_at"] = attr["datetime"] or ""
            if tag == "a" and attr.get("href") and not self.article["url"]:
                self.article["url"] = urljoin(BASE_URL, attr["href"] or "")
                self.capture = "title"
                self.buffer = []
            elif tag == "a" and self.article["url"] and not self.article["episode"]:
                self.capture = "episode"
                self.buffer = []
            elif tag == "time" and not self.article["starts_at"]:
                self.capture = "time"
                self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.article is None:
            return
        if self.capture and tag in {"a", "time"}:
            value = " ".join("".join(self.buffer).split())
            if value:
                self.article[self.capture] = value
            self.capture = None
            self.buffer = []
        if tag == "article":
            self.article_depth -= 1
            if self.article_depth == 0:
                self._finish_article()
                self.article = None

    def _finish_article(self) -> None:
        assert self.article is not None
        title, language = infer_language(self.article["title"], self.patterns)
        if not title or (
            self.enabled_languages is not None and language not in self.enabled_languages
        ):
            return
        episode_match = re.search(
            r"(?:Episode|Episodes)\s+(?:\d+[-–])?(\d+)", self.article["episode"], re.I
        )
        starts_at = self.article["starts_at"]
        try:
            parsed = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError:
            return
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        self.releases.append(
            Release(
                title,
                language,
                int(episode_match.group(1)) if episode_match else None,
                parsed.isoformat(),
                self.article["url"],
            )
        )


def parse_calendar(
    html: str,
    enabled_languages: set[str] | None = None,
    patterns: dict[str, list[str]] | None = None,
) -> list[Release]:
    if not isinstance(html, str) or not html:
        raise ValueError("calendar HTML must be a non-empty string")
    if "Just a moment..." in html and "challenges.cloudflare.com" in html:
        raise RuntimeError("Crunchyroll returned a Cloudflare challenge")
    parser = _CalendarParser(enabled_languages, patterns)
    parser.feed(html)
    if not parser.releases:
        raise RuntimeError("calendar contained no matching releases; page format may have changed")
    return parser.releases


def normalize_title(value: str) -> str:
    value, _ = infer_language(value)
    value = re.sub(r"\s+\([^()]+\)\s*$", "", value)
    value = re.sub(r"\s+Season\s+\d+\b", "", value, flags=re.I)
    value = re.sub(r"\s+\d+(?:st|nd|rd|th)\s+Season\b", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid readable JSON: {exc}") from exc


def load_watching(path: Path) -> list[str]:
    data = _read_json(path, "watchlist")
    entries = data.get("shows") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("watchlist must contain a 'shows' list")
    result: list[str] = []
    for entry in entries:
        if isinstance(entry, str) and entry.strip():
            result.append(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("title"), str):
            aliases = entry.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
                raise ValueError("watchlist aliases must be a list of strings")
            result.extend([entry["title"], *aliases])
        else:
            raise ValueError("each watchlist entry must be a title string or object with a title")
    return [key for item in result if (key := normalize_title(item))]


def load_language_config(path: Path) -> tuple[set[str], dict[str, list[str]]]:
    data = _read_json(path, "language config")
    if not isinstance(data, dict):
        raise ValueError("language config must be a JSON object")
    enabled = data.get("enabled")
    patterns = data.get("patterns")
    if not isinstance(enabled, list) or not enabled or not all(
        isinstance(item, str) and item.strip() for item in enabled
    ):
        raise ValueError("language config 'enabled' must be a non-empty list of strings")
    if not isinstance(patterns, dict) or not all(
        isinstance(key, str)
        and isinstance(values, list)
        and values
        and all(isinstance(value, str) and value.strip() for value in values)
        for key, values in patterns.items()
    ):
        raise ValueError("language config 'patterns' must map names to non-empty string lists")
    if any(language not in patterns for language in enabled):
        raise ValueError("every enabled language must have at least one pattern")
    return set(enabled), patterns


def discovery_dates(anchor: date, samples: int = 20, days: int = 90) -> list[date]:
    if not isinstance(anchor, date):
        raise ValueError("discovery anchor must be a date")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 1:
        raise ValueError("discovery samples must be a positive integer")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("discovery days must be a positive integer")
    start = anchor - timedelta(days=days)
    step = days / max(samples - 1, 1)
    return [start + timedelta(days=round(index * step)) for index in range(samples)]


def _load_discovery_state(path: Path | None) -> dict[str, dict]:
    if path is None or not path.exists():
        return {}
    data = _read_json(path, "discovery state")
    shows = data.get("shows") if isinstance(data, dict) else None
    if not isinstance(shows, dict):
        raise ValueError("discovery state must contain a 'shows' object")
    return shows


def _save_discovery_state(path: Path | None, shows: dict[str, dict]) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"shows": shows}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValueError(f"could not write discovery state {path}: {exc}") from exc


def discover(
    fetcher=fetch_calendar,
    samples: int = 20,
    days: int = 90,
    anchor: date | None = None,
    state_path: Path | None = None,
) -> dict:
    anchor = anchor or previous_week_start()
    languages: dict[str, int] = {}
    shows: dict[str, dict] = {}
    errors: list[str] = []
    for sample_date in discovery_dates(anchor, samples, days):
        try:
            releases = parse_calendar(fetcher(sample_date), enabled_languages=None)
        except (RuntimeError, ValueError) as exc:
            errors.append(f"{sample_date.isoformat()}: {exc}")
            continue
        for release in releases:
            languages[release.language] = languages.get(release.language, 0) + 1
            key = normalize_title(release.title)
            item = shows.setdefault(
                key,
                {
                    "title": release.title,
                    "release_count": 0,
                    "first_seen": release.starts_at[:10],
                    "last_seen": release.starts_at[:10],
                    "languages": [],
                },
            )
            item["release_count"] += 1
            item["first_seen"] = min(item["first_seen"], release.starts_at[:10])
            item["last_seen"] = max(item["last_seen"], release.starts_at[:10])
            if release.language not in item["languages"]:
                item["languages"].append(release.language)
    if not shows:
        raise RuntimeError("discovery found no releases; errors: " + "; ".join(errors))

    previous = _load_discovery_state(state_path)
    current = sorted(shows.values(), key=lambda item: (-item["release_count"], item["title"]))
    merged = dict(previous)
    for key, item in shows.items():
        old = previous.get(key, {})
        item["first_seen"] = min(item["first_seen"], old.get("first_seen", item["first_seen"]))
        item["seen_before"] = key in previous
        merged[key] = {field: value for field, value in item.items() if field != "seen_before"}
    _save_discovery_state(state_path, merged)
    return {
        "anchor": anchor.isoformat(),
        "days": days,
        "samples": samples,
        "languages": dict(sorted(languages.items())),
        "new_shows": [item for item in current if not item["seen_before"]],
        "seen_shows": [item for item in current if item["seen_before"]],
        "errors": errors,
    }


def discover_season(
    season: str,
    fetcher=fetch_season_shows,
    state_path: Path | None = None,
) -> dict:
    season = validate_season(season)
    shows = fetcher(season)
    if not isinstance(shows, list) or not all(isinstance(show, SeasonalShow) for show in shows):
        raise RuntimeError("season fetcher returned invalid show data")
    previous = _load_discovery_state(state_path)
    current: list[dict] = []
    merged = dict(previous)
    for show in shows:
        key = normalize_title(show.title)
        item = {
            "show_key": key,
            "title": show.title,
            "url": show.url,
            "season": season,
            "seen_before": key in previous,
        }
        current.append(item)
        merged[key] = {field: value for field, value in item.items() if field != "seen_before"}
    _save_discovery_state(state_path, merged)
    return {
        "season": season,
        "show_count": len(current),
        "new_shows": [item for item in current if not item["seen_before"]],
        "seen_shows": [item for item in current if item["seen_before"]],
    }


def filter_releases(releases: list[Release], watching: list[str]) -> list[Release]:
    if not watching:
        return []
    watched_titles = {normalize_title(item) for item in watching}
    return [release for release in releases if normalize_title(release.title) in watched_titles]


def make_ics(releases: list[Release], calendar_name: str = "Crunchyroll") -> str:
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//crunchyCalendar//EN",
        f"X-WR-CALNAME:{escape(calendar_name)}",
    ]
    for release in releases:
        start = datetime.fromisoformat(release.starts_at).astimezone(timezone.utc)
        uid_source = f"{release.title}|{release.episode}|{release.starts_at}|{release.language}"
        uid = hashlib.sha256(uid_source.encode()).hexdigest()[:24]
        summary = f"{release.title} - Episode {release.episode}" if release.episode else release.title
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}@crunchy-calendar",
                f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{escape(summary)}",
                f"DESCRIPTION:{escape(release.language)}\\n{escape(release.url)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape Crunchyroll schedules without a browser")
    parser.add_argument("--date", help="Monday starting the target week (YYYY-MM-DD)")
    parser.add_argument("--watching", type=Path, default=Path("data/watching.json"))
    parser.add_argument("--format", choices=("json", "ics"), default="json")
    parser.add_argument("--languages", type=Path, default=Path("data/languages.json"))
    parser.add_argument("--discover", action="store_true", help="update the seasonal discovery ledger")
    parser.add_argument("--discovery-state", type=Path, default=Path("data/discovery.json"))
    parser.add_argument("--season", help="season slug, e.g. summer-2026; defaults to the current season")
    parser.add_argument("--all", action="store_true", help="ignore the watchlist")
    args = parser.parse_args(argv)
    try:
        if args.discover:
            report = discover_season(args.season or current_season(), state_path=args.discovery_state)
            json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
            return 0

        week = parse_monday(args.date) if args.date else previous_week_start()
        enabled_languages, language_patterns = load_language_config(args.languages)
        releases = parse_calendar(fetch_calendar(week), enabled_languages, language_patterns)
        selected = releases if args.all else filter_releases(releases, load_watching(args.watching))
        if args.format == "ics":
            sys.stdout.write(make_ics(selected))
        else:
            json.dump(
                {
                    "week_start": week.isoformat(),
                    "languages": sorted(enabled_languages),
                    "releases": [asdict(item) for item in selected],
                },
                sys.stdout,
                indent=2,
                ensure_ascii=False,
            )
            sys.stdout.write("\n")
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
