from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
from pathlib import Path
import sys
import tempfile

from liquipedia_ical.calendar import build_calendar, read_previous_events
from liquipedia_ical.matches import (
    DEFAULT_ALLOWLIST,
    LiquipediaError,
    fetch_matches_html,
    load_allowlist,
    parse_upcoming_matches,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an iCalendar feed of Liquipedia Tier 1 Dota 2 matches."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dota2-matches.ics"),
        help="calendar path (default: dota2-matches.ics)",
    )
    parser.add_argument(
        "--user-agent",
        help="contact-bearing Liquipedia User-Agent; defaults to LIQUIPEDIA_USER_AGENT",
    )
    parser.add_argument(
        "--tier2-allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="text file of allowed Tier 2 tournament names (default: bundled allowlist)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="API request timeout in seconds (default: 30)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    user_agent = args.user_agent or os.environ.get("LIQUIPEDIA_USER_AGENT")
    if not user_agent:
        repository = os.environ.get("GITHUB_REPOSITORY")
        if repository:
            user_agent = f"LiquipediaIcal/1.0 (https://github.com/{repository})"
    if not user_agent:
        print(
            "error: set LIQUIPEDIA_USER_AGENT to identify the project and provide contact info",
            file=sys.stderr,
        )
        return 2

    output = args.output.resolve()
    previous = output.read_bytes().decode("utf-8") if output.exists() else None

    try:
        allowlist = load_allowlist(args.tier2_allowlist)
        html = fetch_matches_html(
            user_agent=user_agent, timeout=args.timeout, include_tier_two=bool(allowlist)
        )
        matches = parse_upcoming_matches(html, tier_two_allowlist=allowlist)
        calendar = build_calendar(matches, datetime.now(UTC), previous)
    except (LiquipediaError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    total_events = len(read_previous_events(calendar))
    result_summary = (
        f"{total_events} total matches; {len(matches)} currently returned by Liquipedia"
    )
    if previous == calendar:
        print(f"Calendar is unchanged ({result_summary}): {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output, calendar)
    print(f"Wrote {result_summary} to {output}")
    return 0


def _atomic_write(output: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=output.parent,
        prefix=f".{output.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(output)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
