#!/usr/bin/env python3
"""Download diff/patch files for patch URLs listed in a CSV."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import datetime
import email.utils
import hashlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download patch diffs from a CSV of (localId, patch_url)."
    )
    parser.add_argument(
        "--input",
        default="unique_patch_urls.csv",
        help="Input CSV path (default: unique_patch_urls.csv).",
    )
    parser.add_argument(
        "--out-dir",
        default="patch_diffs",
        help="Output directory for diff files (default: patch_diffs).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process first N rows.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N rows before processing.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
        help="HTTP timeout in seconds (default: 25).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Sleep between requests in seconds (default: 0).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of concurrent download workers (default: 8).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Retries per URL candidate for transient failures like HTTP 429 (default: 4).",
    )
    parser.add_argument(
        "--retry-base-s",
        type=float,
        default=1.0,
        help="Base delay for exponential retry backoff in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--retry-max-s",
        type=float,
        default=30.0,
        help="Maximum delay for retry backoff in seconds (default: 30).",
    )
    return parser.parse_args()


class RunLogger:
    """Thread-safe logger that writes to both console and a log file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._fh = path.open("w", encoding="utf-8")

    def log(self, message: str, error: bool = False) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} {message}"
        stream = sys.stderr if error else sys.stdout
        with self._lock:
            print(line, file=stream, flush=True)
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def sanitize_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "entry"


def normalize_patch_url(url: str) -> str:
    """Normalize known broken URL formats."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parsed.query or ""

    # Sourceware plain commit diff endpoint.
    # Convert:
    #   /git/?...;a=commitdiff;h=<40-hex-commit>
    # To:
    #   /git/?...;a=commitdiff_plain;h=<40-hex-commit>
    if host == "sourceware.org" and path == "/git/":
        fixed_query, count = re.subn(
            r"(^|[;&])a=commitdiff(?=($|[;&]))",
            r"\1a=commitdiff_plain",
            query,
            count=1,
        )
        if count > 0:
            parsed = parsed._replace(scheme="https", query=fixed_query)
            return urllib.parse.urlunparse(parsed)

    # Ghostscript patch-id cleanup and known hash correction.
    # Handles cases like:
    #   /ghostpdl.git/patch?id=<40-hex-commit>.patch
    # and a known bad hash that maps to a replacement commit.
    if host == "cgit.ghostscript.com" and re.fullmatch(r"/ghostpdl\.git/patch/?", path):
        params = urllib.parse.parse_qs(query, keep_blank_values=True)
        id_value = params.get("id", [""])[0]
        match = re.fullmatch(r"([0-9a-fA-F]{40})(?:\.patch)?", id_value)
        if match:
            commit_hash = match.group(1).lower()
            if commit_hash == "f99464b8c9c37ffa9d07f2bc5b088572d5e5ca06":
                commit_hash = "2c3bee693aca9204b5c138bd3e1fbeff83123c5d"
            params["id"] = [commit_hash]

            # Special canonical path for this specific ghostpdl commit.
            if commit_hash == "7861fcad13c497728189feafb41cd57b5b50ea25":
                fixed_path = "/cgi-bin/cgit.cgi/ghostpdl.git/patch/"
            else:
                fixed_path = "/ghostpdl.git/patch"

            parsed = parsed._replace(
                scheme="https",
                path=fixed_path,
                query=urllib.parse.urlencode(params, doseq=True),
            )
            return urllib.parse.urlunparse(parsed)

    # binutils-gdb moved from old GitHub mirror to GitLab canonical location.
    # Convert:
    #   /bminor/binutils-gdb/commit/<40-hex-commit>[.patch|.diff]
    # To:
    #   /gnutools/binutils-gdb/-/commit/<40-hex-commit>[.patch|.diff]
    if host == "github.com":
        match = re.fullmatch(
            r"/bminor/binutils-gdb/commit/([0-9a-fA-F]{40})(\.(?:patch|diff))?",
            path,
        )
        if match:
            commit_hash, suffix = match.groups()
            suffix = suffix or ""
            fixed_path = f"/gnutools/binutils-gdb/-/commit/{commit_hash}{suffix}"
            parsed = parsed._replace(scheme="https", netloc="gitlab.com", path=fixed_path, query="")
            return urllib.parse.urlunparse(parsed)

    # Broken invent.kde.org links sometimes look like:
    #   /<namespace>/<repo>.git<40-hex-commit>[.patch|.diff]
    # Convert to:
    #   /<namespace>/<repo>/-/commit/<40-hex-commit>[.patch|.diff]
    if host == "invent.kde.org":
        match = re.fullmatch(
            r"(/.+?)/([A-Za-z0-9._-]+?)\.git([0-9a-fA-F]{40})(\.(?:patch|diff))?",
            path,
        )
        if match:
            namespace_prefix, repo_name, commit_hash, suffix = match.groups()
            suffix = suffix or ""
            fixed_path = f"{namespace_prefix}/{repo_name}/-/commit/{commit_hash}{suffix}"
            parsed = parsed._replace(scheme="https", path=fixed_path, query=query)
            return urllib.parse.urlunparse(parsed)

    # Broken code.videolan.org links sometimes look like:
    #   /<namespace>/<repo>.git<40-hex-commit>[.patch|.diff]
    # Convert to:
    #   /<namespace>/<repo>/-/commit/<40-hex-commit>[.patch|.diff]
    if host == "code.videolan.org":
        match = re.fullmatch(
            r"(/.+?)/([A-Za-z0-9._-]+?)\.git([0-9a-fA-F]{40})(\.(?:patch|diff))?",
            path,
        )
        if match:
            namespace_prefix, repo_name, commit_hash, suffix = match.groups()
            suffix = suffix or ""
            fixed_path = f"{namespace_prefix}/{repo_name}/-/commit/{commit_hash}{suffix}"
            parsed = parsed._replace(scheme="https", path=fixed_path, query=query)
            return urllib.parse.urlunparse(parsed)

    # jbig2dec mirror moved to GitLab canonical location.
    # Convert:
    #   git://git.ghostscript.com/jbig2dec.git<40-hex-commit>
    # To:
    #   https://gitlab.com/freedesktop-sdk/mirrors/ghostscript/jbig2dec/-/commit/<40-hex-commit>
    if host == "git.ghostscript.com":
        match = re.fullmatch(r"/jbig2dec\.git([0-9a-fA-F]{40})", path)
        if match:
            commit_hash = match.group(1)
            fixed_path = f"/freedesktop-sdk/mirrors/ghostscript/jbig2dec/-/commit/{commit_hash}"
            parsed = parsed._replace(scheme="https", netloc="gitlab.com", path=fixed_path, query="")
            return urllib.parse.urlunparse(parsed)

    # Broken Heptapod URLs sometimes look like:
    #   /<namespace>/<repo><40-hex-commit>
    # Convert to:
    #   /<namespace>/<repo>/-/commit/<40-hex-commit>
    if "heptapod.net" in host and "/-/commit/" not in path:
        segments = [s for s in path.split("/") if s]
        if segments:
            last = segments[-1]
            match = re.fullmatch(r"([A-Za-z0-9._-]+?)([0-9a-fA-F]{40})", last)
            if match:
                repo_name, commit_hash = match.groups()
                fixed_segments = segments[:-1] + [repo_name, "-", "commit", commit_hash]
                fixed_path = "/" + "/".join(fixed_segments)
                parsed = parsed._replace(path=fixed_path)
                return urllib.parse.urlunparse(parsed)

    # Broken GitLab-style URLs sometimes look like:
    #   /<namespace>/<repo>.git<40-hex-commit>
    # Convert to:
    #   /<namespace>/<repo>/-/commit/<40-hex-commit>
    if "gitlab." in host and "/-/commit/" not in path:
        segments = [s for s in path.split("/") if s]
        if segments:
            last = segments[-1]
            match = re.fullmatch(r"([A-Za-z0-9._-]+?)([0-9a-fA-F]{40})", last)
            if match:
                repo_name, commit_hash = match.groups()
                if repo_name.endswith(".git"):
                    repo_name = repo_name[:-4]
                fixed_segments = segments[:-1] + [repo_name, "-", "commit", commit_hash]
                fixed_path = "/" + "/".join(fixed_segments)
                parsed = parsed._replace(path=fixed_path)
                return urllib.parse.urlunparse(parsed)

    # Broken git.libssh.org URLs sometimes look like:
    #   /projects/<repo>.git<40-hex-commit>
    # Convert to:
    #   /projects/<repo>.git/patch/?id=<40-hex-commit>
    if "git.libssh.org" in host:
        segments = [s for s in path.split("/") if s]
        if segments:
            last = segments[-1]
            match = re.fullmatch(r"([A-Za-z0-9._-]+?\.git)([0-9a-fA-F]{40})", last)
            if match:
                repo_name, commit_hash = match.groups()
                fixed_segments = segments[:-1] + [repo_name, "patch"]
                fixed_path = "/" + "/".join(fixed_segments) + "/"
                fixed_query = urllib.parse.urlencode({"id": commit_hash})
                parsed = parsed._replace(path=fixed_path, query=fixed_query)
                return urllib.parse.urlunparse(parsed)

    # Broken ghostscript URLs sometimes look like:
    #   /<repo>.git<40-hex-commit>
    # Convert to:
    #   /<repo>.git/patch?id=<40-hex-commit>
    if "cgit.ghostscript.com" in host:
        segments = [s for s in path.split("/") if s]
        if segments:
            last = segments[-1]
            match = re.fullmatch(r"([A-Za-z0-9._-]+?\.git)([0-9a-fA-F]{40})", last)
            if match:
                repo_name, commit_hash = match.groups()
                fixed_segments = segments[:-1] + [repo_name, "patch"]
                fixed_path = "/" + "/".join(fixed_segments)
                fixed_query = urllib.parse.urlencode({"id": commit_hash})
                parsed = parsed._replace(path=fixed_path, query=fixed_query)
                return urllib.parse.urlunparse(parsed)

    # Broken hg.nginx.org URLs can look like:
    #   /<repo>/rev/<40-hex-commit>
    #   /<repo>/<40-hex-commit>
    #   /<repo><40-hex-commit>
    # Convert all to:
    #   /<repo>/raw-rev/<40-hex-commit>
    if "hg.nginx.org" in host:
        raw_match = re.fullmatch(r"(/.+)/rev/([0-9a-fA-F]{40})/?", path)
        if raw_match:
            repo_prefix, commit_hash = raw_match.groups()
            fixed_path = f"{repo_prefix}/raw-rev/{commit_hash}"
            parsed = parsed._replace(scheme="https", path=fixed_path, query="")
            return urllib.parse.urlunparse(parsed)

        direct_match = re.fullmatch(r"/([A-Za-z0-9._-]+)/([0-9a-fA-F]{40})/?", path)
        if direct_match:
            repo_name, commit_hash = direct_match.groups()
            fixed_path = f"/{repo_name}/raw-rev/{commit_hash}"
            parsed = parsed._replace(scheme="https", path=fixed_path, query="")
            return urllib.parse.urlunparse(parsed)

    if "hg.nginx.org" in host and "/rev/" not in path:
        segments = [s for s in path.split("/") if s]
        if segments:
            last = segments[-1]
            match = re.fullmatch(r"([A-Za-z0-9._-]+?)([0-9a-fA-F]{40})", last)
            if match:
                repo_name, commit_hash = match.groups()
                fixed_segments = segments[:-1] + [repo_name, "raw-rev", commit_hash]
                fixed_path = "/" + "/".join(fixed_segments)
                parsed = parsed._replace(scheme="https", path=fixed_path, query="")
                return urllib.parse.urlunparse(parsed)

    # Broken FFmpeg gitweb links sometimes look like:
    #   /gitweb/<repo>.git/commitdiff/<40-hex-commit>.diff
    # Convert to:
    #   /gitweb/<repo>.git/patch/<40-hex-commit>
    if "git.ffmpeg.org" in host:
        match = re.fullmatch(
            r"(.*/gitweb/[^/]+?\.git)/commitdiff/([0-9a-fA-F]{40})(?:\.diff)?",
            path,
        )
        if match:
            repo_base, commit_hash = match.groups()
            fixed_path = f"{repo_base}/patch/{commit_hash}"
            parsed = parsed._replace(scheme="https", path=fixed_path, query="")
            return urllib.parse.urlunparse(parsed)

    return url


def candidate_urls(url: str) -> list[tuple[str, bool]]:
    """Return (candidate_url, is_googlesource_base64_diff)."""
    url = normalize_patch_url(url)
    out: list[tuple[str, bool]] = []
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    has_query = bool(parsed.query)
    path_has_suffix = parsed.path.endswith(".patch") or parsed.path.endswith(".diff")
    skip_generic_suffix = has_query or host == "hg.nginx.org" or path_has_suffix

    def append_unique(u: str, is_b64: bool = False) -> None:
        if not any(existing == u for existing, _ in out):
            out.append((u, is_b64))

    append_unique(url, False)

    if "github.com" in host and "/commit/" in parsed.path:
        append_unique(url + ".patch", False)
        append_unique(url + ".diff", False)

    if "googlesource.com" in host and "/+/" in parsed.path:
        joiner = "&" if parsed.query else "?"
        append_unique(url + f"{joiner}format=TEXT", True)

    # Generic path suffix variants are only safe for path-style URLs.
    # Query-style patch endpoints (e.g., .../patch?id=...) should not become ...id=....patch.
    if not skip_generic_suffix:
        append_unique(url + ".patch", False)
        append_unique(url + ".diff", False)
    return out


def looks_like_diff(text: str) -> bool:
    markers = ("diff --git ", "\n--- ", "\n+++ ", "\n@@ ", "\nIndex: ")
    if text.startswith("From "):
        return True
    return any(m in text for m in markers)


def detect_soft_block_reason(text: str) -> str | None:
    lower = text.lower()
    checks = [
        ("too many requests", "rate-limited by upstream page"),
        ("rate limit", "rate-limited by upstream page"),
        ("captcha", "blocked by CAPTCHA challenge"),
        ("cloudflare", "blocked by Cloudflare challenge"),
        ("enable javascript", "blocked by JS challenge page"),
        ("making sure you're not a bot", "blocked by anti-bot challenge"),
    ]
    for needle, reason in checks:
        if needle in lower:
            return reason

    if ("<html" in lower or "<!doctype html" in lower) and "diff --git" not in lower:
        return "received HTML page instead of diff"
    return None


def is_anubis_challenge(text: str) -> bool:
    lower = text.lower()
    return "anubis" in lower and (
        "making sure you're not a bot" in lower
        or "protected by anubis" in lower
        or "javascript is required" in lower
    )


def maybe_decode_googlesource(raw: bytes, is_b64: bool) -> bytes:
    if not is_b64:
        return raw
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return raw


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return max(0.0, (dt - now).total_seconds())


def compute_backoff_delay(
    attempt: int, base_delay: float, max_delay: float, retry_after: float | None
) -> float:
    if retry_after is not None:
        return min(max_delay, retry_after)
    exp = base_delay * (2**attempt)
    jitter = random.uniform(0.0, base_delay)
    return min(max_delay, exp + jitter)


def fetch_diff(
    url: str,
    timeout: int,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
) -> tuple[str, bytes]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/x-diff,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    errors: list[str] = []
    retryable_http_codes = {429, 500, 502, 503, 504}

    candidates = candidate_urls(url)
    manual_patch_url = next(
        (
            candidate
            for candidate, _ in candidates
            if candidate.endswith(".patch")
            or "/patch/" in urllib.parse.urlparse(candidate).path
            or urllib.parse.urlparse(candidate).path.endswith("/patch")
        ),
        normalize_patch_url(url),
    )
    manual_challenge_markers = {
        "blocked by js challenge page",
        "blocked by captcha challenge",
        "blocked by cloudflare challenge",
        "blocked by anti-bot challenge",
    }

    for candidate, is_b64 in candidates:
        attempts = 0
        while True:
            attempts += 1
            req = urllib.request.Request(candidate, headers=headers, method="GET")
            content_type = ""
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    body = resp.read()
            except urllib.error.HTTPError as exc:
                should_retry = exc.code in retryable_http_codes and attempts <= max_retries
                if should_retry:
                    retry_after = parse_retry_after(exc.headers.get("Retry-After"))
                    delay = compute_backoff_delay(
                        attempt=attempts - 1,
                        base_delay=retry_base_s,
                        max_delay=retry_max_s,
                        retry_after=retry_after,
                    )
                    time.sleep(delay)
                    continue
                errors.append(f"{candidate} -> HTTP {exc.code} (attempts={attempts})")
                break
            except urllib.error.URLError as exc:
                should_retry = attempts <= max_retries
                if should_retry:
                    delay = compute_backoff_delay(
                        attempt=attempts - 1,
                        base_delay=retry_base_s,
                        max_delay=retry_max_s,
                        retry_after=None,
                    )
                    time.sleep(delay)
                    continue
                errors.append(f"{candidate} -> URL error: {exc.reason} (attempts={attempts})")
                break

            content = maybe_decode_googlesource(body, is_b64)
            text = content.decode("utf-8", errors="replace")
            if is_anubis_challenge(text):
                raise RuntimeError(
                    "Browser challenge detected (Anubis). Manual action required: "
                    f"open this patch URL in your browser, complete the challenge, then rerun: {manual_patch_url}"
                )

            soft_block = detect_soft_block_reason(text)
            if soft_block is not None:
                if soft_block.lower() in manual_challenge_markers:
                    raise RuntimeError(
                        "Browser challenge detected "
                        f"({soft_block}) at {candidate}. Manual action required: "
                        f"open this patch URL in your browser, complete the challenge, then rerun: {manual_patch_url}"
                    )
                if attempts <= max_retries:
                    delay = compute_backoff_delay(
                        attempt=attempts - 1,
                        base_delay=retry_base_s,
                        max_delay=retry_max_s,
                        retry_after=None,
                    )
                    time.sleep(delay)
                    continue
                errors.append(
                    f"{candidate} -> {soft_block} (content-type={content_type or 'unknown'}, attempts={attempts})"
                )
                break

            if looks_like_diff(text):
                return candidate, content
            errors.append(
                f"{candidate} -> not a diff-like response (content-type={content_type or 'unknown'}, attempts={attempts})"
            )
            break

    raise RuntimeError("; ".join(errors) if errors else "no candidate URLs worked")


def download_one(
    idx: int,
    total: int,
    local_id: str,
    patch_url: str,
    timeout: int,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
    out_dir: Path,
    sleep_seconds: float,
) -> tuple[bool, str]:
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    url_hash = hashlib.sha1(patch_url.encode("utf-8")).hexdigest()[:10]
    file_name = f"{sanitize_name(local_id)}_{url_hash}.diff"
    out_path = out_dir / file_name
    try:
        used_url, diff_bytes = fetch_diff(
            patch_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_s=retry_base_s,
            retry_max_s=retry_max_s,
        )
        out_path.write_bytes(diff_bytes)
        return True, f"[{idx}/{total}] OK  {local_id} -> {out_path} (from {used_url})"
    except Exception as exc:
        return False, f"[{idx}/{total}] ERR {local_id} -> {exc}"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(out_dir / "log.txt")
    try:
        if args.limit is not None and args.limit < 0:
            logger.log("Error: --limit must be >= 0", error=True)
            return 2
        if args.offset < 0:
            logger.log("Error: --offset must be >= 0", error=True)
            return 2
        if args.workers <= 0:
            logger.log("Error: --workers must be >= 1", error=True)
            return 2
        if args.max_retries < 0:
            logger.log("Error: --max-retries must be >= 0", error=True)
            return 2
        if args.retry_base_s < 0:
            logger.log("Error: --retry-base-s must be >= 0", error=True)
            return 2
        if args.retry_max_s <= 0:
            logger.log("Error: --retry-max-s must be > 0", error=True)
            return 2
        if not input_path.exists():
            logger.log(f"Error: input CSV not found: {input_path}", error=True)
            return 2

        logger.log(
            "Starting run "
            f"(input={input_path}, out_dir={out_dir}, workers={args.workers}, "
            f"max_retries={args.max_retries}, timeout={args.timeout})"
        )

        with input_path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [(r[0].strip(), r[1].strip()) for r in reader if len(r) >= 2 and r[1].strip()]

        rows = rows[args.offset :]
        if args.limit is not None:
            rows = rows[: args.limit]

        if not rows:
            logger.log("No rows to process.")
            return 0

        total = len(rows)
        ok = 0
        fail = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    download_one,
                    idx,
                    total,
                    local_id,
                    patch_url,
                    args.timeout,
                    args.max_retries,
                    args.retry_base_s,
                    args.retry_max_s,
                    out_dir,
                    args.sleep,
                )
                for idx, (local_id, patch_url) in enumerate(rows, start=1)
            ]

            for future in concurrent.futures.as_completed(futures):
                try:
                    success, message = future.result()
                except Exception as exc:
                    fail += 1
                    logger.log(f"Worker exception: {exc}", error=True)
                    continue
                if success:
                    ok += 1
                    logger.log(message)
                else:
                    fail += 1
                    logger.log(message, error=True)

        logger.log(f"Done. success={ok} failed={fail} total={total}")
        return 0 if fail == 0 else 1
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
