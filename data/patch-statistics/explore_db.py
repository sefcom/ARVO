#!/usr/bin/env python3
"""Lightweight SQLite database explorer."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Sequence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Explore a SQLite .db file from the command line."
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default="arvo.db",
        help="Path to the SQLite database file (default: arvo.db).",
    )
    parser.add_argument(
        "-t",
        "--table",
        action="append",
        dest="tables",
        help="Inspect only this table (can be used multiple times).",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=5,
        help="Number of sample rows to show per table (default: 5).",
    )
    parser.add_argument(
        "--counts",
        action="store_true",
        help="Show row counts for tables.",
    )
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include SQLite system tables.",
    )
    parser.add_argument(
        "--no-samples",
        action="store_true",
        help="Skip sample row previews.",
    )
    parser.add_argument(
        "-q",
        "--query",
        help="Run a custom SQL query after metadata output.",
    )
    return parser.parse_args()


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def format_cell(value: object, max_width: int = 80) -> str:
    if value is None:
        text = "NULL"
    elif isinstance(value, bytes):
        text = f"<bytes:{len(value)}>"
    else:
        text = str(value)
    if len(text) > max_width:
        return text[: max_width - 1] + "..."
    return text


def print_grid(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    rows = list(rows)
    if not headers:
        print("(no columns)")
        return
    display_rows = [[format_cell(cell) for cell in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in display_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    header_line = " | ".join(h.ljust(widths[idx]) for idx, h in enumerate(headers))
    sep_line = "-+-".join("-" * widths[idx] for idx in range(len(headers)))
    print(header_line)
    print(sep_line)
    if not display_rows:
        print("(no rows)")
        return
    for row in display_rows:
        print(" | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)))


def load_objects(conn: sqlite3.Connection, include_system: bool) -> list[sqlite3.Row]:
    query = """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE type IN ('table', 'view')
    """
    if not include_system:
        query += " AND name NOT LIKE 'sqlite_%'"
    query += " ORDER BY type, name"
    cur = conn.execute(query)
    return list(cur.fetchall())


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    cur = conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})")
    return list(cur.fetchall())


def table_count(conn: sqlite3.Connection, table_name: str) -> int | None:
    try:
        cur = conn.execute(f"SELECT COUNT(*) AS c FROM {quote_identifier(table_name)}")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return None


def sample_rows(
    conn: sqlite3.Connection, table_name: str, limit: int
) -> tuple[list[str], list[sqlite3.Row]]:
    cur = conn.execute(
        f"SELECT * FROM {quote_identifier(table_name)} LIMIT ?",
        (limit,),
    )
    headers = [item[0] for item in (cur.description or [])]
    rows = list(cur.fetchall())
    return headers, rows


def get_asan_report_for_patch(
    patch_id: int | str, db_path: str | Path = "arvo.db"
) -> str | None:
    """Return the ASAN crash report (crash_output) for a patch localId."""
    return get_sanitizer_report_for_patch(
        patch_id, db_path=db_path, sanitizers=("asan",)
    )


def get_sanitizer_report_for_patch(
    patch_id: int | str,
    db_path: str | Path = "arvo.db",
    sanitizers: Sequence[str] = ("asan", "msan", "tsan", "ubsan"),
) -> str | None:
    """Return crash_output for a patch localId and sanitizer set."""
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"database file not found: {db_file}")

    try:
        local_id = int(str(patch_id).strip())
    except ValueError as exc:
        raise ValueError(f"invalid patch id: {patch_id}") from exc
    if not sanitizers:
        raise ValueError("sanitizers must not be empty")
    sanitizer_list = [str(item).strip().lower() for item in sanitizers if str(item).strip()]
    if not sanitizer_list:
        raise ValueError("sanitizers must not be empty")

    placeholders = ", ".join("?" for _ in sanitizer_list)

    uri = f"file:{db_file.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute(
            f"""
            SELECT crash_output
            FROM arvo
            WHERE localId = ?
              AND sanitizer IS NOT NULL
              AND lower(sanitizer) IN ({placeholders})
            LIMIT 1
            """,
            (local_id, *sanitizer_list),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None
    return row[0]


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)

    if args.limit < 0:
        print("Error: --limit must be >= 0", file=sys.stderr)
        return 2
    if not db_path.exists():
        print(f"Error: database file not found: {db_path}", file=sys.stderr)
        return 2

    uri = f"file:{db_path.resolve()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        print(f"Error: could not open database: {exc}", file=sys.stderr)
        return 1

    conn.row_factory = sqlite3.Row
    try:
        objects = load_objects(conn, include_system=args.include_system)
        if not objects:
            print(f"Database: {db_path}")
            print("No tables or views found.")
            return 0

        object_rows = []
        for obj in objects:
            if args.counts:
                count = "-"
                if obj["type"] == "table":
                    table_row_count = table_count(conn, obj["name"])
                    count = "?" if table_row_count is None else str(table_row_count)
                object_rows.append((obj["type"], obj["name"], count))
            else:
                object_rows.append((obj["type"], obj["name"]))

        print(f"Database: {db_path}")
        print("\nObjects:")
        headers = ["type", "name"]
        if args.counts:
            headers.append("rows")
        print_grid(headers, object_rows)

        selected_tables = set(args.tables or [])
        table_objects = [o for o in objects if o["type"] == "table"]
        if selected_tables:
            table_objects = [o for o in table_objects if o["name"] in selected_tables]
            missing = selected_tables - {o["name"] for o in table_objects}
            for table_name in sorted(missing):
                print(f"\nWarning: table not found: {table_name}")

        for table in table_objects:
            table_name = table["name"]
            print(f"\n=== TABLE: {table_name} ===")
            sql = table["sql"] or "(no CREATE SQL available)"
            print(f"Schema:\n{sql}")

            cols = table_columns(conn, table_name)
            col_rows = [
                (
                    col["name"],
                    col["type"] or "",
                    "YES" if col["notnull"] == 0 else "NO",
                    "YES" if col["pk"] else "NO",
                    format_cell(col["dflt_value"]),
                )
                for col in cols
            ]
            print("\nColumns:")
            print_grid(["name", "type", "nullable", "pk", "default"], col_rows)

            if not args.no_samples:
                print(f"\nSample rows (limit {args.limit}):")
                headers, rows = sample_rows(conn, table_name, args.limit)
                print_grid(headers, rows)

        if args.query:
            print("\n=== CUSTOM QUERY ===")
            print(args.query)
            cur = conn.execute(args.query)
            headers = [item[0] for item in (cur.description or [])]
            rows = cur.fetchmany(args.limit if args.limit > 0 else 100)
            print_grid(headers, rows)

        return 0
    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
