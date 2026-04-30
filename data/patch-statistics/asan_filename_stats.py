#!/usr/bin/env python3
"""Compute filename/function overlap between patch diffs and sanitizer reports."""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from explore_db import get_sanitizer_report_for_patch

try:
    from unidiff import PatchSet
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "Error: unidiff is not installed. Run with the project venv "
        "(e.g., ./venv/bin/python asan_filename_stats.py ...)."
    ) from exc


DIFF_ID_RE = re.compile(r"^(?P<id>\d+)(?:_[^.]+)?(?:\.diff)?$")
DEFAULT_SANITIZERS = ("asan", "msan", "tsan", "ubsan")
FILE_CHAR_RE = re.compile(r"[A-Za-z0-9_.-]")
FUNCTION_CHAR_RE = re.compile(r"[A-Za-z0-9_:$~]")
FUNC_TOKEN_RE = re.compile(
    r"([A-Za-z_~][A-Za-z0-9_~]*(?:::[A-Za-z_~][A-Za-z0-9_~]*)*)\s*\("
)
STACK_FRAME_RE = re.compile(
    r"^\s*#(?P<idx>\d+)\s+0x[0-9a-fA-F]+\s+in\s+(?P<symbol>.+)$"
)
FUNC_DEF_LINE_RE = re.compile(
    r"""^\s*
    (?:[A-Za-z_~][A-Za-z0-9_~<>\*&\s:,]*\s+)?      # return type / qualifiers
    (?P<name>[A-Za-z_~][A-Za-z0-9_~]*(?:::[A-Za-z_~][A-Za-z0-9_~]*)*)
    \s*\(
    [^;{}]*\)
    \s*(?:const\b\s*)?(?:\{|$)
    """,
    re.VERBOSE,
)

CONTROL_OR_NONFUNC_TOKENS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "sizeof",
    "alignof",
    "decltype",
    "typeof",
    "defined",
    "new",
    "delete",
    "operator",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "For each .diff file, parse modified filenames/functions with unidiff and "
            "check whether they appear in sanitizer crash reports for that patch id."
        )
    )
    parser.add_argument(
        "--diff-dir",
        default="patch_diffs",
        help="Directory containing patch diff files (default: patch_diffs).",
    )
    parser.add_argument(
        "--pattern",
        default="*.diff",
        help="Glob pattern for diff files (default: *.diff).",
    )
    parser.add_argument(
        "--db",
        default="arvo.db",
        help="Path to SQLite database (default: arvo.db).",
    )
    parser.add_argument(
        "--sanitizers",
        default=",".join(DEFAULT_SANITIZERS),
        help=(
            "Comma-separated sanitizer names to include "
            "(default: asan,msan,tsan,ubsan)."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Print progress every N files to stderr (default: 500, 0 disables).",
    )
    parser.add_argument(
        "--show-examples",
        type=int,
        default=10,
        help="Number of matching patch examples to print (default: 10, 0 disables).",
    )
    parser.add_argument(
        "--max-stack-index-report",
        type=int,
        default=10,
        help=(
            "Maximum stack index to print in detailed index distributions "
            "(default: 10)."
        ),
    )
    parser.add_argument(
        "--print-parse-failures",
        action="store_true",
        help="Print each parse failure with the exception reason.",
    )
    parser.add_argument(
        "--print-missing-sanitizer",
        action="store_true",
        help=(
            "Print patch id and filename for patches without a matching sanitizer report."
        ),
    )
    parser.add_argument(
        "--print-missing-asan",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def parse_sanitizers(value: str) -> tuple[str, ...]:
    items = [part.strip().lower() for part in value.split(",")]
    cleaned = tuple(item for item in items if item)
    if not cleaned:
        raise ValueError("sanitizer list is empty")
    return cleaned


def extract_patch_id(diff_path: Path) -> int:
    match = DIFF_ID_RE.match(diff_path.name)
    if not match:
        raise ValueError(f"cannot extract patch id from filename: {diff_path.name}")
    return int(match.group("id"))


def normalize_diff_path(path: str | None) -> str | None:
    if not path:
        return None
    value = path.strip().replace("\\", "/")
    if not value or value == "/dev/null":
        return None
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    if not value or value == "/dev/null":
        return None
    return value


def parse_modified_filenames(diff_text: str) -> tuple[set[str], int]:
    patch = PatchSet(io.StringIO(diff_text))
    names: set[str] = set()
    for patched_file in patch:
        for raw_name in (
            getattr(patched_file, "path", None),
            getattr(patched_file, "source_file", None),
            getattr(patched_file, "target_file", None),
        ):
            norm = normalize_diff_path(raw_name)
            if not norm:
                continue
            names.add(norm)
            names.add(Path(norm).name)
    return names, len(patch)


def _is_function_char(char: str) -> bool:
    return bool(FUNCTION_CHAR_RE.fullmatch(char))


def _normalize_function_name(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if "(" in value:
        value = value.split("(", 1)[0].strip()
    value = re.sub(r"\b(const|noexcept|volatile)\b\s*$", "", value).strip()
    if not value:
        return None
    if value in CONTROL_OR_NONFUNC_TOKENS:
        return None
    last = value.split("::")[-1]
    if last in CONTROL_OR_NONFUNC_TOKENS:
        return None
    return value


def _function_name_variants(raw: str) -> set[str]:
    normalized = _normalize_function_name(raw)
    if not normalized:
        return set()
    variants = {normalized}
    if "::" in normalized:
        variants.add(normalized.split("::")[-1])
    return variants


def _extract_function_from_header(header: str) -> set[str]:
    matches = [m.group(1) for m in FUNC_TOKEN_RE.finditer(header)]
    if not matches:
        return set()
    for token in reversed(matches):
        variants = _function_name_variants(token)
        if variants:
            return variants
    return set()


def _extract_functions_from_changed_line(line: str) -> set[str]:
    match = FUNC_DEF_LINE_RE.match(line)
    if not match:
        return set()
    return _function_name_variants(match.group("name"))


def parse_modified_functions(diff_text: str) -> tuple[set[str], int]:
    patch = PatchSet(io.StringIO(diff_text))
    functions: set[str] = set()
    for patched_file in patch:
        for hunk in patched_file:
            if getattr(hunk, "section_header", ""):
                functions.update(_extract_function_from_header(hunk.section_header))
            for line in hunk:
                if line.line_type not in {"+", "-"}:
                    continue
                functions.update(_extract_functions_from_changed_line(line.value))
    return functions, len(patch)


def _is_file_char(char: str) -> bool:
    return bool(FILE_CHAR_RE.fullmatch(char))


def token_in_report(
    report_lower: str,
    token_lower: str,
    is_boundary_char,
) -> bool:
    if not token_lower:
        return False
    if "/" in token_lower:
        return token_lower in report_lower

    start = 0
    token_len = len(token_lower)
    while True:
        idx = report_lower.find(token_lower, start)
        if idx == -1:
            return False
        left_ok = idx == 0 or not is_boundary_char(report_lower[idx - 1])
        right_idx = idx + token_len
        right_ok = right_idx == len(report_lower) or not is_boundary_char(
            report_lower[right_idx]
        )
        if left_ok and right_ok:
            return True
        start = idx + 1


def find_matching_tokens(tokens: set[str], report: str, is_boundary_char) -> set[str]:
    report_lower = report.lower()
    matches: set[str] = set()
    for token in tokens:
        token_lower = token.lower()
        if token_in_report(report_lower, token_lower, is_boundary_char):
            matches.add(token)
    return matches


def extract_stack_function_positions(report: str) -> dict[str, set[int]]:
    """Return function -> stack index set from all stack traces in the report."""
    positions: dict[str, set[int]] = {}
    for raw_line in report.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        frame_match = STACK_FRAME_RE.match(line)
        if not frame_match:
            continue

        frame_idx = int(frame_match.group("idx"))
        symbol = frame_match.group("symbol").strip()
        if " /" in symbol:
            symbol = symbol.split(" /", 1)[0].strip()
        if " (" in symbol:
            symbol = symbol.split(" (", 1)[0].strip()
        variants = _function_name_variants(symbol)
        for name in variants:
            if name not in positions:
                positions[name] = set()
            positions[name].add(frame_idx)
    return positions


def match_functions_with_positions(
    modified_functions: set[str],
    report_positions: dict[str, set[int]],
) -> dict[str, set[int]]:
    report_lower_positions: dict[str, set[int]] = {}
    for report_name, indexes in report_positions.items():
        key = report_name.lower()
        if key not in report_lower_positions:
            report_lower_positions[key] = set()
        report_lower_positions[key].update(indexes)

    matches: dict[str, set[int]] = {}
    for modified_name in modified_functions:
        key = modified_name.lower()
        if key in report_lower_positions:
            matches[modified_name] = set(report_lower_positions[key])
    return matches


def main() -> int:
    args = parse_args()
    diff_dir = Path(args.diff_dir)
    if args.max_stack_index_report < 0:
        print("Error: --max-stack-index-report must be >= 0", file=sys.stderr)
        return 2
    try:
        sanitizers = parse_sanitizers(args.sanitizers)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print_missing_reports = args.print_missing_sanitizer or args.print_missing_asan

    if not diff_dir.exists() or not diff_dir.is_dir():
        print(f"Error: diff directory not found: {diff_dir}", file=sys.stderr)
        return 2

    diff_files = sorted(p for p in diff_dir.rglob(args.pattern) if p.is_file())
    if not diff_files:
        print(
            f"Error: no files matched pattern {args.pattern!r} in {diff_dir}",
            file=sys.stderr,
        )
        return 2

    total_files = len(diff_files)
    parse_ok = 0
    parse_failed = 0
    id_failed = 0
    no_matching_report = 0
    with_matching_report = 0
    filename_matched_patches = 0
    function_matched_patches = 0
    both_matched_patches = 0
    patches_with_modified_functions = 0
    matching_report_patches_with_modified_functions = 0
    modified_file_count_total = 0
    modified_function_count_total = 0
    patch_file_entry_count_total = 0

    report_cache: dict[int, str | None] = {}
    report_function_positions_cache: dict[int, dict[str, set[int]]] = {}
    filename_matched_examples: list[tuple[int, str, list[str]]] = []
    function_matched_examples: list[tuple[int, str, list[str]]] = []
    parse_failures: list[tuple[str, str]] = []
    missing_report_entries: list[tuple[int, str]] = []
    function_match_index_patch_counts: dict[int, int] = {}
    function_match_index_occurrence_counts: dict[int, int] = {}
    first_function_match_index_counts: dict[int, int] = {}

    for idx, diff_path in enumerate(diff_files, start=1):
        try:
            patch_id = extract_patch_id(diff_path)
        except ValueError:
            id_failed += 1
            if args.progress_every > 0 and idx % args.progress_every == 0:
                print(f"[progress] {idx}/{total_files}", file=sys.stderr)
            continue

        try:
            diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
            modified_files, patch_file_entries = parse_modified_filenames(diff_text)
            modified_functions, _ = parse_modified_functions(diff_text)
            parse_ok += 1
            modified_file_count_total += len(modified_files)
            modified_function_count_total += len(modified_functions)
            patch_file_entry_count_total += patch_file_entries
            if modified_functions:
                patches_with_modified_functions += 1
        except Exception as exc:
            parse_failed += 1
            reason = f"{type(exc).__name__}: {exc}".replace("\n", "\\n")
            parse_failures.append((diff_path.name, reason))
            if args.progress_every > 0 and idx % args.progress_every == 0:
                print(f"[progress] {idx}/{total_files}", file=sys.stderr)
            continue

        if patch_id not in report_cache:
            report_cache[patch_id] = get_sanitizer_report_for_patch(
                patch_id, args.db, sanitizers=sanitizers
            )
        report = report_cache[patch_id]

        if not report:
            no_matching_report += 1
            missing_report_entries.append((patch_id, diff_path.name))
            if args.progress_every > 0 and idx % args.progress_every == 0:
                print(f"[progress] {idx}/{total_files}", file=sys.stderr)
            continue

        with_matching_report += 1
        if modified_functions:
            matching_report_patches_with_modified_functions += 1
        file_matches = find_matching_tokens(modified_files, report, _is_file_char)

        if patch_id not in report_function_positions_cache:
            report_function_positions_cache[patch_id] = (
                extract_stack_function_positions(report)
            )
        report_function_positions = report_function_positions_cache[patch_id]
        function_match_positions = match_functions_with_positions(
            modified_functions, report_function_positions
        )
        function_matches = set(function_match_positions)
        patch_match_indexes: set[int] = set()
        for indexes in function_match_positions.values():
            patch_match_indexes.update(indexes)

        if file_matches:
            filename_matched_patches += 1
            if (
                args.show_examples > 0
                and len(filename_matched_examples) < args.show_examples
            ):
                filename_matched_examples.append(
                    (
                        patch_id,
                        diff_path.name,
                        sorted(file_matches, key=lambda item: (len(item), item))[:8],
                    )
                )

        if function_matches:
            function_matched_patches += 1
            for idx_value in sorted(patch_match_indexes):
                function_match_index_patch_counts[idx_value] = (
                    function_match_index_patch_counts.get(idx_value, 0) + 1
                )
            for indexes in function_match_positions.values():
                for idx_value in sorted(indexes):
                    function_match_index_occurrence_counts[idx_value] = (
                        function_match_index_occurrence_counts.get(idx_value, 0) + 1
                    )
            first_idx = min(patch_match_indexes)
            first_function_match_index_counts[first_idx] = (
                first_function_match_index_counts.get(first_idx, 0) + 1
            )
            if (
                args.show_examples > 0
                and len(function_matched_examples) < args.show_examples
            ):
                token_examples = []
                for name in sorted(function_match_positions):
                    idx_text = ",".join(str(i) for i in sorted(function_match_positions[name]))
                    token_examples.append(f"{name}@{idx_text}")
                function_matched_examples.append(
                    (
                        patch_id,
                        diff_path.name,
                        token_examples[:8],
                    )
                )

        if file_matches and function_matches:
            both_matched_patches += 1

        if args.progress_every > 0 and idx % args.progress_every == 0:
            print(f"[progress] {idx}/{total_files}", file=sys.stderr)

    pct_filename_among_reports = (
        (filename_matched_patches / with_matching_report) * 100.0
        if with_matching_report
        else 0.0
    )
    pct_function_among_reports = (
        (function_matched_patches / with_matching_report) * 100.0
        if with_matching_report
        else 0.0
    )
    pct_both_among_reports = (
        (both_matched_patches / with_matching_report) * 100.0
        if with_matching_report
        else 0.0
    )
    pct_filename_among_all = (
        (filename_matched_patches / total_files) * 100.0 if total_files else 0.0
    )
    pct_function_among_all = (
        (function_matched_patches / total_files) * 100.0 if total_files else 0.0
    )
    pct_both_among_all = (
        (both_matched_patches / total_files) * 100.0 if total_files else 0.0
    )
    pct_function_among_reports_with_patch_funcs = (
        (function_matched_patches / matching_report_patches_with_modified_functions)
        * 100.0
        if matching_report_patches_with_modified_functions
        else 0.0
    )
    avg_modified_tokens = (
        (modified_file_count_total / parse_ok) if parse_ok else 0.0
    )
    avg_modified_functions = (
        (modified_function_count_total / parse_ok) if parse_ok else 0.0
    )
    avg_patch_entries = (
        (patch_file_entry_count_total / parse_ok) if parse_ok else 0.0
    )

    print(f"diff_directory: {diff_dir}")
    print(f"pattern: {args.pattern}")
    print(f"sanitizers: {','.join(sanitizers)}")
    print(f"total_diff_files: {total_files}")
    print(f"parse_ok: {parse_ok}")
    print(f"parse_failed: {parse_failed}")
    print(f"id_parse_failed: {id_failed}")
    print(f"patches_with_matching_sanitizer_report: {with_matching_report}")
    print(f"patches_without_matching_sanitizer_report: {no_matching_report}")
    print(f"patches_with_modified_function_tokens: {patches_with_modified_functions}")
    print(
        "matching_report_patches_with_modified_function_tokens: "
        f"{matching_report_patches_with_modified_functions}"
    )
    print(
        "patches_with_filename_match_in_report: "
        f"{filename_matched_patches}"
    )
    print(
        "patches_with_function_match_in_report: "
        f"{function_matched_patches}"
    )
    print(
        "patches_with_filename_and_function_match_in_report: "
        f"{both_matched_patches}"
    )
    print(
        "percent_filename_match_among_matching_report_patches: "
        f"{pct_filename_among_reports:.2f}%"
    )
    print(
        "percent_function_match_among_matching_report_patches: "
        f"{pct_function_among_reports:.2f}%"
    )
    print(
        "percent_filename_and_function_match_among_matching_report_patches: "
        f"{pct_both_among_reports:.2f}%"
    )
    print(
        "percent_function_match_among_matching_report_patches_with_function_tokens: "
        f"{pct_function_among_reports_with_patch_funcs:.2f}%"
    )
    print("function_match_stack_index_patch_counts:")
    if function_match_index_patch_counts:
        shown = 0
        omitted = 0
        for idx_value in sorted(function_match_index_patch_counts):
            if idx_value > args.max_stack_index_report:
                omitted += 1
                continue
            count = function_match_index_patch_counts[idx_value]
            pct = (count / function_matched_patches) * 100.0 if function_matched_patches else 0.0
            print(f"  - #{idx_value}: {count} patches ({pct:.2f}% of function-matched patches)")
            shown += 1
        if shown == 0:
            print("  (none in shown range)")
        if omitted:
            print(f"  - ... {omitted} higher indexes omitted (>{args.max_stack_index_report})")
    else:
        print("  (none)")
    print("function_match_stack_index_occurrence_counts:")
    if function_match_index_occurrence_counts:
        shown = 0
        omitted = 0
        for idx_value in sorted(function_match_index_occurrence_counts):
            if idx_value > args.max_stack_index_report:
                omitted += 1
                continue
            count = function_match_index_occurrence_counts[idx_value]
            print(f"  - #{idx_value}: {count} matched-function occurrences")
            shown += 1
        if shown == 0:
            print("  (none in shown range)")
        if omitted:
            print(f"  - ... {omitted} higher indexes omitted (>{args.max_stack_index_report})")
    else:
        print("  (none)")
    print("first_function_match_index_counts:")
    if first_function_match_index_counts:
        shown = 0
        omitted = 0
        for idx_value in sorted(first_function_match_index_counts):
            if idx_value > args.max_stack_index_report:
                omitted += 1
                continue
            count = first_function_match_index_counts[idx_value]
            pct = (count / function_matched_patches) * 100.0 if function_matched_patches else 0.0
            print(f"  - #{idx_value}: {count} patches ({pct:.2f}%)")
            shown += 1
        if shown == 0:
            print("  (none in shown range)")
        if omitted:
            print(f"  - ... {omitted} higher indexes omitted (>{args.max_stack_index_report})")
    else:
        print("  (none)")
    top_indexes = [0, 1, 2, 3]
    for idx_value in top_indexes:
        count = function_match_index_patch_counts.get(idx_value, 0)
        pct = (count / function_matched_patches) * 100.0 if function_matched_patches else 0.0
        print(
            f"function_match_at_index_{idx_value}: "
            f"{count} patches ({pct:.2f}% of function-matched patches)"
        )
    print(
        "percent_filename_match_among_all_diff_files: "
        f"{pct_filename_among_all:.2f}%"
    )
    print(
        "percent_function_match_among_all_diff_files: "
        f"{pct_function_among_all:.2f}%"
    )
    print(
        "percent_filename_and_function_match_among_all_diff_files: "
        f"{pct_both_among_all:.2f}%"
    )
    print(f"avg_modified_filename_tokens_per_parseable_patch: {avg_modified_tokens:.2f}")
    print(f"avg_modified_function_tokens_per_parseable_patch: {avg_modified_functions:.2f}")
    print(f"avg_patch_file_entries_per_parseable_patch: {avg_patch_entries:.2f}")

    if filename_matched_examples:
        print("filename_matched_examples:")
        for patch_id, diff_name, tokens in filename_matched_examples:
            token_text = ", ".join(tokens)
            print(f"  - {patch_id} ({diff_name}): {token_text}")
    if function_matched_examples:
        print("function_matched_examples:")
        for patch_id, diff_name, tokens in function_matched_examples:
            token_text = ", ".join(tokens)
            print(f"  - {patch_id} ({diff_name}): {token_text}")
    if args.print_parse_failures:
        print("parse_failures:")
        if not parse_failures:
            print("  (none)")
        else:
            for diff_name, reason in parse_failures:
                print(f"  - {diff_name}: {reason}")
    if print_missing_reports:
        print("missing_sanitizer_reports:")
        if not missing_report_entries:
            print("  (none)")
        else:
            for patch_id, diff_name in missing_report_entries:
                print(f"  - {patch_id} ({diff_name})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
