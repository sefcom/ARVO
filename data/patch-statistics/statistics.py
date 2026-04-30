#!/usr/bin/env python3
"""Plot files-changed-per-patch statistics using unidiff + matplotlib."""

from __future__ import annotations

import argparse
import io
import math
import sys
from pathlib import Path

try:
    import matplotlib
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "Error: matplotlib is not installed. Install it with: pip install matplotlib"
    ) from exc

import matplotlib.pyplot as plt  # noqa: E402

try:
    from unidiff import PatchSet
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "Error: unidiff is not installed. Install it with: pip install unidiff"
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot distribution: x = files changed, y = number of patches "
            "for one diff file or a directory of .diff files."
        )
    )
    parser.add_argument(
        "input",
        help="Diff file path, directory path containing patch files, or '-' for stdin.",
    )
    parser.add_argument(
        "--pattern",
        default="*.diff",
        help="Filename pattern when input is a directory (default: *.diff).",
    )
    parser.add_argument(
        "--save",
        default=None,
        help="Optional output image path (e.g., stats.png) instead of showing a window.",
    )
    parser.add_argument(
        "--x-max",
        type=int,
        default=20,
        help="Maximum files-changed value shown on x-axis (default: 20).",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def count_files_changed(diff_text: str) -> int:
    patch = PatchSet(io.StringIO(diff_text))
    return len(patch)


def parse_patch_metrics(diff_text: str) -> tuple[int, int, int]:
    patch = PatchSet(io.StringIO(diff_text))
    files_changed = len(patch)
    lines_added = 0
    lines_removed = 0
    for patched_file in patch:
        file_added = getattr(patched_file, "added", None)
        file_removed = getattr(patched_file, "removed", None)
        if isinstance(file_added, int) and isinstance(file_removed, int):
            lines_added += file_added
            lines_removed += file_removed
            continue
        for hunk in patched_file:
            lines_added += int(getattr(hunk, "added", 0))
            lines_removed += int(getattr(hunk, "removed", 0))
    return files_changed, lines_added, lines_removed


def collect_inputs(input_arg: str, pattern: str) -> list[Path]:
    if input_arg == "-":
        return []

    input_path = Path(input_arg)
    if not input_path.exists():
        raise FileNotFoundError(f"input path not found: {input_path}")

    if input_path.is_file():
        return [input_path]

    files = sorted(p for p in input_path.rglob(pattern) if p.is_file())
    if not files:
        raise FileNotFoundError(
            f"no files matched pattern {pattern!r} under directory: {input_path}"
        )
    return files


def average_files_changed(counts: list[int]) -> float:
    if not counts:
        raise ValueError("cannot compute average for empty data")
    return sum(counts) / len(counts)


def percent_single_file_patches(counts: list[int]) -> float:
    if not counts:
        raise ValueError("cannot compute percentage for empty data")
    single = sum(1 for value in counts if value == 1)
    return (single / len(counts)) * 100.0


def mean_per_patch(values: list[int]) -> float:
    if not values:
        raise ValueError("cannot compute mean for empty data")
    return sum(values) / len(values)


def percentile_nearest_rank(values: list[int], percentile: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile for empty data")
    if percentile < 0 or percentile > 100:
        raise ValueError("percentile must be in [0, 100]")
    sorted_vals = sorted(values)
    if percentile == 0:
        return float(sorted_vals[0])
    rank = math.ceil((percentile / 100.0) * len(sorted_vals))
    idx = min(max(rank - 1, 0), len(sorted_vals) - 1)
    return float(sorted_vals[idx])


def quartiles_from_raw_counts(values: list[int]) -> tuple[float, float, float]:
    if not values:
        raise ValueError("cannot compute quartiles for empty data")
    q1 = percentile_nearest_rank(values, 25.0)
    q2 = percentile_nearest_rank(values, 50.0)
    q3 = percentile_nearest_rank(values, 75.0)
    return q1, q2, q3


def median_per_patch(values: list[int]) -> float:
    if not values:
        raise ValueError("cannot compute median for empty data")
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_vals[mid])
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def plot_counts(counts: list[int], save_path: str | None, x_max: int) -> str:
    if x_max < 1:
        raise ValueError("--x-max must be >= 1")

    overflow = sum(1 for value in counts if value > x_max)
    clipped_counts = [value if value <= x_max else x_max for value in counts]
    bin_edges = [value - 0.5 for value in range(1, x_max + 2)]

    plt.figure(figsize=(12, 5))
    plt.hist(clipped_counts, bins=bin_edges, rwidth=0.85)
    plt.xlabel("Files Changed")
    plt.ylabel("Number of Patches")
    plt.title("Histogram of Files Changed per Patch")
    plt.grid(True, linestyle="--", linewidth=0.5, alpha=0.7)
    plt.xlim(0.5, x_max + 0.5)
    if x_max <= 50:
        tick_positions = list(range(1, x_max + 1))
        tick_labels = [str(i) for i in tick_positions]
        if overflow:
            tick_labels[-1] = f"{x_max}+"
        plt.xticks(tick_positions, tick_labels)
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150)
        plt.close()
        return "saved"

    backend = matplotlib.get_backend()
    if "agg" in backend.lower():
        plt.close()
        raise RuntimeError(
            f"matplotlib backend '{backend}' is non-interactive, cannot show window. "
            "Use --save <file.png> or run with an interactive backend (e.g., TkAgg/QtAgg)."
        )

    plt.show()
    plt.close()
    return "shown"


def main() -> int:
    args = parse_args()

    try:
        input_files = collect_inputs(args.input, args.pattern)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    counts: list[int] = []
    lines_added_per_patch: list[int] = []
    lines_removed_per_patch: list[int] = []

    if args.input == "-":
        try:
            files_changed, lines_added, lines_removed = parse_patch_metrics(sys.stdin.read())
            counts.append(files_changed)
            lines_added_per_patch.append(lines_added)
            lines_removed_per_patch.append(lines_removed)
        except Exception as exc:
            print(f"Error: failed to parse stdin diff with unidiff: {exc}", file=sys.stderr)
            return 1
    else:
        for patch_file in input_files:
            try:
                files_changed, lines_added, lines_removed = parse_patch_metrics(read_text(patch_file))
                counts.append(files_changed)
                lines_added_per_patch.append(lines_added)
                lines_removed_per_patch.append(lines_removed)
            except Exception as exc:
                print(
                    f"Warning: failed to parse {patch_file} with unidiff: {exc}",
                    file=sys.stderr,
                )

    if not counts:
        print("Error: no parseable patch files found.", file=sys.stderr)
        return 1

    try:
        mode = plot_counts(counts, args.save, args.x_max)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    avg_files = average_files_changed(counts)
    pct_single = percent_single_file_patches(counts)
    mean_added = mean_per_patch(lines_added_per_patch)
    mean_removed = mean_per_patch(lines_removed_per_patch)
    median_added = median_per_patch(lines_added_per_patch)
    median_removed = median_per_patch(lines_removed_per_patch)
    p90_files_changed = percentile_nearest_rank(counts, 90.0)
    p90_added = percentile_nearest_rank(lines_added_per_patch, 90.0)
    p90_removed = percentile_nearest_rank(lines_removed_per_patch, 90.0)
    q1_files_changed, q2_files_changed, q3_files_changed = quartiles_from_raw_counts(counts)
    print(f"patches_counted: {len(counts)}")
    print(f"average_files_changed: {avg_files:.4f}")
    print(f"q1_files_changed: {q1_files_changed:.4f}")
    print(f"q2_files_changed: {q2_files_changed:.4f}")
    print(f"q3_files_changed: {q3_files_changed:.4f}")
    print(f"p90_files_changed: {p90_files_changed:.4f}")
    print(f"percent_single_file_patches: {pct_single:.2f}%")
    print(f"mean_lines_added_per_patch: {mean_added:.4f}")
    print(f"mean_lines_removed_per_patch: {mean_removed:.4f}")
    print(f"median_lines_added_per_patch: {median_added:.4f}")
    print(f"median_lines_removed_per_patch: {median_removed:.4f}")
    print(f"p90_lines_added_per_patch: {p90_added:.4f}")
    print(f"p90_lines_removed_per_patch: {p90_removed:.4f}")
    print(f"Counted {len(counts)} parseable patches.")
    print(f"On average, each patch changes {avg_files:.4f} files.")
    print(
        f"At least 25% of patches changed {q1_files_changed:.4f} files or fewer (Q1)."
    )
    print(
        f"At least 50% of patches changed {q2_files_changed:.4f} files or fewer (Q2/median)."
    )
    print(
        f"At least 75% of patches changed {q3_files_changed:.4f} files or fewer (Q3)."
    )
    print(
        f"At least 90% of patches changed {p90_files_changed:.4f} files or fewer (P90)."
    )
    print(f"{pct_single:.2f}% of patches change exactly one file.")
    print(f"The mean lines added per patch is {mean_added:.4f}.")
    print(f"The mean lines removed per patch is {mean_removed:.4f}.")
    print(f"The median lines added per patch is {median_added:.4f}.")
    print(f"The median lines removed per patch is {median_removed:.4f}.")
    print(
        f"At least 90% of patches added {p90_added:.4f} lines or fewer (P90 lines added)."
    )
    print(
        f"At least 90% of patches removed {p90_removed:.4f} lines or fewer (P90 lines removed)."
    )
    if mode == "saved":
        print(f"plot_saved: {args.save}")
    else:
        print("plot_shown: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
