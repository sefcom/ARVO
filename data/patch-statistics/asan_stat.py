#!/usr/bin/env python3
"""Print a sanitizer crash report for a given diff filename."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from explore_db import get_sanitizer_report_for_patch


DIFF_ID_RE = re.compile(r"^(?P<id>\d+)(?:_[^.]+)?(?:\.diff)?$")
DEFAULT_SANITIZERS = ("asan", "msan", "tsan", "ubsan")


def extract_patch_id(diff_name: str) -> int:
    name = Path(diff_name).name
    match = DIFF_ID_RE.match(name)
    if not match:
        raise ValueError(
            f"could not extract patch id from diff name '{diff_name}'"
        )
    return int(match.group("id"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print sanitizer crash report for a patch diff name."
    )
    parser.add_argument(
        "diff_name",
        help="Diff filename or path (e.g. 42470026_4e06aa6a0f.diff).",
    )
    parser.add_argument(
        "--db",
        default="arvo.db",
        help="Path to SQLite DB (default: arvo.db).",
    )
    parser.add_argument(
        "--sanitizers",
        default=",".join(DEFAULT_SANITIZERS),
        help=(
            "Comma-separated sanitizer names to include "
            "(default: asan,msan,tsan,ubsan)."
        ),
    )
    return parser.parse_args()


def parse_sanitizers(value: str) -> tuple[str, ...]:
    items = [part.strip().lower() for part in value.split(",")]
    cleaned = tuple(item for item in items if item)
    if not cleaned:
        raise ValueError("sanitizer list is empty")
    return cleaned


def main() -> int:
    args = parse_args()
    try:
        sanitizers = parse_sanitizers(args.sanitizers)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        patch_id = extract_patch_id(args.diff_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        report = get_sanitizer_report_for_patch(
            patch_id, args.db, sanitizers=sanitizers
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: failed to fetch sanitizer report: {exc}", file=sys.stderr)
        return 1

    if not report:
        print(
            f"No matching sanitizer report found for patch id {patch_id}.",
            file=sys.stderr,
        )
        return 1

    sys.stdout.write(report)
    if not report.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
