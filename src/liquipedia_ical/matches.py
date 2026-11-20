from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import gzip
import json
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag


API_URL = "https://liquipedia.net/dota2/api.php"
MATCHES_PAGE_URL = "https://liquipedia.net/dota2/Liquipedia:Matches"
DEFAULT_ALLOWLIST = Path(__file__).parent / "data" / "tier2_allowlist.txt"
CARD_CLASSES = ("match-info", "match-ticker-card")


def load_allowlist(path: Path = DEFAULT_ALLOWLIST) -> set[str]:
    """Read one tournament name per line, ignoring blank lines and comments."""
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _tournament_key(name: str) -> str:
    name = " ".join(name.casefold().split())
    return re.sub(r"\bseason\s+(\d+)\b", r"s\1", name)


def is_qualifier_event(*labels: str) -> bool:
    """Recognize qualifiers, play-ins, and CQ/OQ abbreviations."""
    return any(
        re.search(
            r"\b(?:quals?|qualifiers?|qualification|[co]q\d*|play[\s\-–‑]*ins?)\b",
            unquote(label).replace("_", " "),
            re.IGNORECASE,
        )
        for label in labels
    )


def _is_qualifier_card(tournament: Tag | None, stage: str) -> bool:
    labels = [_text(tournament), stage]
    if tournament is not None:
        for link in tournament.select("a"):
            labels.extend(str(link.get(attribute, "")) for attribute in ("href", "title"))
    return is_qualifier_event(*labels)


class LiquipediaError(RuntimeError):
    """Raised when the Liquipedia response cannot safely produce a calendar."""


@dataclass(frozen=True, slots=True)
class Match:
    start: datetime
    team1: str
    team2: str
    tournament: str
    series_format: str
    source_url: str
    source_id: str | None = None
    liquipedia_tier: int = 1

    @property
    def duration(self) -> timedelta:
        """Return a conservative estimate because Liquipedia has no end time."""
        best_of = re.fullmatch(r"Bo(\d+)", self.series_format, re.IGNORECASE)
        hours = int(best_of.group(1)) if best_of else 3
        return timedelta(hours=max(1, min(hours, 8)))


def _matches_wikitext(tier: int) -> str:
    return (
        f'<div id="liquipedia-tier-{tier}-matches">'
        "{{#invoke:Lua|invoke|module=MatchTicker/Custom|fn=mainPage|dev=false|"
        f"type=upcoming|limit=50|filterbuttons-liquipediatier={tier}"
        "}}</div>"
    )


def fetch_matches_html(
    user_agent: str, timeout: float = 30, *, include_tier_two: bool = False
) -> str:
    """Render separate, source-filtered tiers in one MediaWiki API request."""
    parameters = urlencode(
        {
            "action": "parse",
            "title": "Liquipedia:Matches",
            "text": _matches_wikitext(1)
            + (_matches_wikitext(2) if include_tier_two else ""),
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        }
    )
    request = Request(
        f"{API_URL}?{parameters}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": user_agent,
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
            payload = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                payload = gzip.decompress(payload)
            data = json.loads(payload.decode("utf-8"))
    except Exception as error:
        raise LiquipediaError(f"Liquipedia API request failed: {error}") from error

    if "error" in data:
        message = data["error"].get("info", "unknown API error")
        raise LiquipediaError(f"Liquipedia API returned an error: {message}")

    try:
        return data["parse"]["text"]
    except (KeyError, TypeError) as error:
        raise LiquipediaError(
            "Liquipedia API response did not contain parsed HTML"
        ) from error


def parse_upcoming_matches(
    html: str, *, tier_two_allowlist: set[str] | None = None
) -> list[Match]:
    """Parse Tier 1 and allowlisted Tier 2 matches, excluding qualifiers."""
    soup = BeautifulSoup(html, "html.parser")
    allowed = {_tournament_key(name) for name in tier_two_allowlist or ()}
    matches = []
    tiers = (1, 2) if allowed else (1,)
    for tier in tiers:
        section = soup.select_one(f"#liquipedia-tier-{tier}-matches")
        if section is None:
            raise LiquipediaError(f"Liquipedia response is missing the Tier {tier} section")

        for timer in section.select(".timer-object[data-timestamp]"):
            if timer.find_parent(class_=CARD_CLASSES) is None:
                raise LiquipediaError(f"Unrecognized match card in Tier {tier}")

        for card in section.find_all(class_=CARD_CLASSES):
            tournament = card.select_one(
                ".match-info-tournament-name, .match-ticker-card-tournament-name"
            )
            stage, series_format = _stage_and_format(card)
            if _is_qualifier_card(tournament, stage):
                continue
            name = _text(tournament) or "Dota 2"
            if stage:
                name = f"{name} - {stage}"
            key = _tournament_key(name)
            if tier == 2 and not any(
                key == entry or key.startswith(entry + " - ") for entry in allowed
            ):
                continue
            link = tournament.select_one("a[href]") if tournament is not None else None
            matches.append(_parse_match_card(card, tier, name, series_format, link))

    return matches


def _stage_and_format(card: Tag) -> tuple[str, str]:
    header = card.select_one(".match-ticker-card__header > div")
    if header is not None:
        label = _text(header)
        stage, separator, series_format = label.rpartition(" - ")
        if separator or re.fullmatch(r"Bo\d+", series_format, re.IGNORECASE):
            return stage, series_format or "TBD"
        return label, "TBD"
    format_text = _text(card.select_one(".match-info-header-scoreholder-lower"))
    return "", format_text.strip("() ") or "TBD"


def _parse_match_card(
    card: Tag,
    liquipedia_tier: int,
    tournament: str,
    series_format: str,
    tournament_link: Tag | None,
) -> Match:
    timestamp = card.select_one(".timer-object[data-timestamp]")
    opponent_slots = card.select(".match-info-header-opponent, .match-ticker-card__opponent")
    if timestamp is None or len(opponent_slots) != 2:
        raise LiquipediaError("Match card requires a timestamp and two opponent slots")

    try:
        start = datetime.fromtimestamp(int(timestamp["data-timestamp"]), UTC)
    except (TypeError, ValueError, OSError, OverflowError) as error:
        raise LiquipediaError("Match card has an invalid timestamp") from error

    team1 = _opponent_label(opponent_slots[0])
    team2 = _opponent_label(opponent_slots[1])
    source_id, match_url = _match_identity_and_url(card)
    source_url = match_url or _absolute_href(tournament_link) or MATCHES_PAGE_URL

    return Match(
        start=start,
        team1=team1,
        team2=team2,
        tournament=tournament,
        series_format=series_format,
        source_url=source_url,
        source_id=source_id,
        liquipedia_tier=liquipedia_tier,
    )


def _opponent_label(opponent: Tag) -> str:
    """Read team names as well as bracket seeds such as "A3" and "B4"."""
    for selector in (".team-shortname", ".name", ".brkts-opponent-block-literal"):
        label = _text(opponent.select_one(selector))
        if label:
            return label
    return _text(opponent) or "TBD"


def _match_identity_and_url(card: Tag) -> tuple[str | None, str | None]:
    for link in card.select(".match-info-links a[href]"):
        href = str(link.get("href", ""))
        parsed = urlparse(unquote(href))
        query_title = parse_qs(parsed.query).get("title", [None])[0]
        path_title = unquote(parsed.path.rsplit("/", 1)[-1]).replace("_", " ")
        title = query_title or path_title
        if title and title.startswith("Match:"):
            normalized = title.replace(" ", "_")
            path = quote(normalized, safe=":_-.")
            return normalized, f"https://liquipedia.net/dota2/{path}"
    return None, None


def _absolute_href(link: Tag | None) -> str | None:
    if link is None or not link.get("href"):
        return None
    return urljoin(MATCHES_PAGE_URL, str(link["href"]))


def _text(element: Tag | None) -> str:
    return element.get_text(" ", strip=True) if element is not None else ""
