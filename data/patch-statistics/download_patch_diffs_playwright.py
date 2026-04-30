#!/usr/bin/env python3
"""Download patch diffs with Playwright fallback for JS-protected links."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from download_patch_diffs import (
    candidate_urls,
    compute_backoff_delay,
    detect_soft_block_reason,
    is_anubis_challenge,
    looks_like_diff,
    maybe_decode_googlesource,
    normalize_patch_url,
    parse_retry_after,
    sanitize_name,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download patch diffs with Playwright fallback for JS challenges."
    )
    parser.add_argument("--input", default="unique_patch_urls.csv")
    parser.add_argument("--out-dir", default="patch_diffs_playwright")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-base-s", type=float, default=1.0)
    parser.add_argument("--retry-max-s", type=float, default=20.0)
    parser.add_argument(
        "--playwright-browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
    )
    parser.add_argument(
        "--playwright-headful",
        action="store_true",
        help="Run Playwright with visible browser window.",
    )
    parser.add_argument(
        "--playwright-timeout-ms",
        type=int,
        default=30000,
        help="Playwright navigation/request timeout in ms.",
    )
    parser.add_argument(
        "--playwright-max-wait-s",
        type=float,
        default=60.0,
        help="Max wait per challenged URL while Playwright solves JS challenge.",
    )
    return parser.parse_args()


class RunLogger:
    """Thread-safe logger that writes to both console and log file."""

    def __init__(self, path: Path) -> None:
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


@dataclass
class DownloadResult:
    idx: int
    total: int
    local_id: str
    out_path: Path
    status: str  # ok | err | challenge
    message: str
    challenge_url: str | None = None
    manual_patch_url: str | None = None


class JSChallengeRequired(RuntimeError):
    def __init__(self, reason: str, challenge_url: str, manual_patch_url: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.challenge_url = challenge_url
        self.manual_patch_url = manual_patch_url


def output_path_for(local_id: str, patch_url: str, out_dir: Path) -> Path:
    url_hash = hashlib.sha1(patch_url.encode("utf-8")).hexdigest()[:10]
    return out_dir / f"{sanitize_name(local_id)}_{url_hash}.diff"


def is_completed_download(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def normalize_libreoffice_patch_url(url: str) -> str:
    """Fix malformed LibreOffice commit URLs like /core<sha> to /core/+/<sha>."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "git.libreoffice.org":
        return url

    match = re.fullmatch(r"/core([0-9a-fA-F]{40})(\.(?:patch|diff))?/?", parsed.path or "")
    if match:
        commit_hash, suffix = match.groups()
        fixed_path = f"/core/+/{commit_hash}{suffix or ''}"
        parsed = parsed._replace(scheme="https", path=fixed_path)
        return urllib.parse.urlunparse(parsed)
    return url


def normalize_gnupg_patch_url(url: str) -> str:
    """Fix malformed GnuPG links like git://git.gnupg.org/gnupg.git<sha>."""
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "git.gnupg.org":
        return url

    match = re.fullmatch(r"/gnupg\.git([0-9a-fA-F]{40})(\.(?:patch|diff))?/?", parsed.path or "")
    if match:
        commit_hash, suffix = match.groups()
        fixed_path = f"/gpg/gnupg/commit/{commit_hash}{suffix or ''}"
        parsed = parsed._replace(
            scheme="https",
            netloc="github.com",
            path=fixed_path,
            query="",
        )
        return urllib.parse.urlunparse(parsed)
    return url


def normalize_patch_url_for_playwright(url: str) -> str:
    url = normalize_libreoffice_patch_url(url)
    url = normalize_gnupg_patch_url(url)
    return url


def is_libreoffice_text_diff_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "git.libreoffice.org":
        return False
    if urllib.parse.parse_qs(parsed.query).get("format", [""])[0].upper() != "TEXT":
        return False
    path = urllib.parse.unquote(parsed.path or "")
    return bool(re.fullmatch(r"/core/\+/[0-9a-fA-F]{40}\^!/?", path))


def libreoffice_text_diff_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "git.libreoffice.org":
        return None

    path = urllib.parse.unquote(parsed.path or "")
    if is_libreoffice_text_diff_url(url):
        return urllib.parse.urlunparse(parsed._replace(scheme="https"))

    match = re.fullmatch(r"/core/\+/([0-9a-fA-F]{40})/?", path)
    if not match:
        return None

    commit_hash = match.group(1)
    text_path = f"/core/+/{commit_hash}%5E!/"
    parsed = parsed._replace(scheme="https", path=text_path, query="format=TEXT")
    return urllib.parse.urlunparse(parsed)


def is_googlesource_text_diff_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if "googlesource.com" not in parsed.netloc.lower():
        return False
    if urllib.parse.parse_qs(parsed.query).get("format", [""])[0].upper() != "TEXT":
        return False
    path = urllib.parse.unquote(parsed.path or "")
    return bool(re.fullmatch(r"/.+/\+/[0-9a-fA-F]{40}\^!/?", path))


def googlesource_text_diff_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if "googlesource.com" not in parsed.netloc.lower():
        return None

    path = urllib.parse.unquote(parsed.path or "")
    diff_match = re.fullmatch(r"(.*/\+/)([0-9a-fA-F]{40})\^!/?", path)
    if diff_match:
        prefix, commit_hash = diff_match.groups()
    else:
        commit_match = re.fullmatch(r"(.*/\+/)([0-9a-fA-F]{40})/?", path)
        if not commit_match:
            return None
        prefix, commit_hash = commit_match.groups()

    text_path = f"{prefix}{commit_hash}%5E!/"
    query_items = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() != "format"
    ]
    query_items.append(("format", "TEXT"))
    parsed = parsed._replace(
        scheme="https",
        path=text_path,
        query=urllib.parse.urlencode(query_items, doseq=True),
    )
    return urllib.parse.urlunparse(parsed)


def is_base64_diff_url(url: str) -> bool:
    return is_libreoffice_text_diff_url(url) or is_googlesource_text_diff_url(url)


def candidate_urls_with_libreoffice(url: str) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []

    def append_or_mark_b64(candidate_url: str, is_b64: bool) -> None:
        for idx, (existing, existing_is_b64) in enumerate(out):
            if existing == candidate_url:
                if is_b64 and not existing_is_b64:
                    out[idx] = (existing, True)
                return
        out.append((candidate_url, is_b64))

    for text_candidate in (libreoffice_text_diff_url(url), googlesource_text_diff_url(url)):
        if text_candidate is not None:
            append_or_mark_b64(text_candidate, True)

    for candidate, is_b64 in candidate_urls(url):
        append_or_mark_b64(candidate, is_b64)

    if is_base64_diff_url(url):
        append_or_mark_b64(url, True)

    return out


def pick_manual_patch_url(url: str) -> str:
    url = normalize_patch_url_for_playwright(url)
    candidates = candidate_urls_with_libreoffice(url)
    return next(
        (
            candidate
            for candidate, _ in candidates
            if candidate.endswith(".patch")
            or "/patch/" in candidate
            or candidate.endswith("/patch")
        ),
        next((candidate for candidate, is_b64 in candidates if is_b64), normalize_patch_url(url)),
    )


def fetch_diff_http(
    url: str,
    timeout: int,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
) -> tuple[str, bytes]:
    url = normalize_patch_url_for_playwright(url)
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
    retryable_http_codes = {429, 500, 502, 503, 504}
    errors: list[str] = []
    candidates = candidate_urls_with_libreoffice(url)
    manual_patch_url = pick_manual_patch_url(url)
    challenge_markers = {
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
                if exc.code in retryable_http_codes and attempts <= max_retries:
                    retry_after = parse_retry_after(exc.headers.get("Retry-After"))
                    delay = compute_backoff_delay(attempts - 1, retry_base_s, retry_max_s, retry_after)
                    time.sleep(delay)
                    continue
                errors.append(f"{candidate} -> HTTP {exc.code} (attempts={attempts})")
                break
            except urllib.error.URLError as exc:
                if attempts <= max_retries:
                    delay = compute_backoff_delay(attempts - 1, retry_base_s, retry_max_s, None)
                    time.sleep(delay)
                    continue
                errors.append(f"{candidate} -> URL error: {exc.reason} (attempts={attempts})")
                break

            content = maybe_decode_googlesource(body, is_b64)
            text = content.decode("utf-8", errors="replace")

            if is_anubis_challenge(text):
                raise JSChallengeRequired(
                    "Anubis browser challenge detected",
                    candidate,
                    manual_patch_url,
                )

            soft_block = detect_soft_block_reason(text)
            if soft_block is not None:
                if soft_block.lower() in challenge_markers:
                    raise JSChallengeRequired(
                        f"{soft_block} (content-type={content_type or 'unknown'})",
                        candidate,
                        manual_patch_url,
                    )
                if attempts <= max_retries:
                    delay = compute_backoff_delay(attempts - 1, retry_base_s, retry_max_s, None)
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


def download_one_http(
    idx: int,
    total: int,
    local_id: str,
    patch_url: str,
    out_dir: Path,
    timeout: int,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
    sleep_seconds: float,
) -> DownloadResult:
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    out_path = output_path_for(local_id, patch_url, out_dir)
    try:
        used_url, diff_bytes = fetch_diff_http(
            patch_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_s=retry_base_s,
            retry_max_s=retry_max_s,
        )
        out_path.write_bytes(diff_bytes)
        return DownloadResult(
            idx=idx,
            total=total,
            local_id=local_id,
            out_path=out_path,
            status="ok",
            message=f"[{idx}/{total}] OK {local_id} -> {out_path} ({used_url})",
        )
    except JSChallengeRequired as exc:
        return DownloadResult(
            idx=idx,
            total=total,
            local_id=local_id,
            out_path=out_path,
            status="challenge",
            message=f"[{idx}/{total}] WN {local_id} -> solving js challenge",
            challenge_url=exc.challenge_url,
            manual_patch_url=exc.manual_patch_url,
        )
    except Exception as exc:
        return DownloadResult(
            idx=idx,
            total=total,
            local_id=local_id,
            out_path=out_path,
            status="err",
            message=f"[{idx}/{total}] ERR {local_id} -> {exc}",
        )


class PlaywrightChallengeSolver:
    def __init__(
        self,
        browser_name: str,
        headful: bool,
        timeout_ms: int,
        max_wait_s: float,
    ) -> None:
        self.browser_name = browser_name
        self.headful = headful
        self.timeout_ms = timeout_ms
        self.max_wait_s = max_wait_s
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "PlaywrightChallengeSolver":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright not installed. Install with: pip install playwright && playwright install"
            ) from exc

        self._pw = sync_playwright().start()
        browser_type = getattr(self._pw, self.browser_name)
        self._browser = browser_type.launch(
            headless=not self.headful,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = self._browser.new_context(
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        self._context.set_default_timeout(self.timeout_ms)
        self._context.set_default_navigation_timeout(self.timeout_ms)
        self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def fetch_patch_after_challenge(self, challenge_url: str, patch_url: str) -> bytes:
        assert self._context is not None
        page = self._context.new_page()
        try:
            page.goto(challenge_url, wait_until="domcontentloaded")
            patch_url_is_b64 = is_base64_diff_url(patch_url)
            deadline = time.time() + self.max_wait_s
            while time.time() < deadline:
                try:
                    resp = page.goto(patch_url, wait_until="domcontentloaded")
                except Exception:
                    resp = None

                # 1) Try response body when available.
                if resp is not None:
                    try:
                        body = maybe_decode_googlesource(resp.body(), patch_url_is_b64)
                        text = body.decode("utf-8", errors="replace")
                        if looks_like_diff(text):
                            return body
                    except Exception:
                        pass

                # 2) Try page text (useful when diff is rendered in browser).
                try:
                    body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                except Exception:
                    body_text = ""
                if patch_url_is_b64 and body_text:
                    try:
                        decoded_body = maybe_decode_googlesource(body_text.encode("utf-8"), True)
                        decoded_text = decoded_body.decode("utf-8", errors="replace")
                        if looks_like_diff(decoded_text):
                            return decoded_body
                    except Exception:
                        pass
                if looks_like_diff(body_text):
                    return body_text.encode("utf-8")

                page.wait_for_timeout(1500 + int(random.uniform(0, 600)))
                try:
                    page.goto(challenge_url, wait_until="domcontentloaded")
                except Exception:
                    pass

            host = urllib.parse.urlparse(patch_url).netloc
            raise RuntimeError(
                "Playwright could not clear JS challenge in time. "
                f"Try running with --playwright-headful and a larger --playwright-max-wait-s for {host}. "
                f"Open manually if needed: {patch_url}"
            )
        finally:
            page.close()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(out_dir / "log.txt")

    try:
        if not input_path.exists():
            logger.log(f"Error: input CSV not found: {input_path}", error=True)
            return 2
        if args.workers <= 0:
            logger.log("Error: --workers must be >= 1", error=True)
            return 2
        if args.max_retries < 0:
            logger.log("Error: --max-retries must be >= 0", error=True)
            return 2
        if args.offset < 0:
            logger.log("Error: --offset must be >= 0", error=True)
            return 2
        if args.limit is not None and args.limit < 0:
            logger.log("Error: --limit must be >= 0", error=True)
            return 2

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
        indexed_rows = [
            (idx, local_id, patch_url, output_path_for(local_id, patch_url, out_dir))
            for idx, (local_id, patch_url) in enumerate(rows, start=1)
        ]
        existing_completed = sum(
            1 for _, _, _, out_path in indexed_rows if is_completed_download(out_path)
        )
        first_incomplete_pos = next(
            (pos for pos, (_, _, _, out_path) in enumerate(indexed_rows) if not is_completed_download(out_path)),
            None,
        )
        if first_incomplete_pos is None:
            logger.log(f"Done. success={total} failed=0 total={total} (already downloaded)")
            return 0

        start_idx, start_local_id, _, _ = indexed_rows[first_incomplete_pos]
        resume_rows = indexed_rows[first_incomplete_pos:]
        pending_rows = [
            (idx, local_id, patch_url)
            for idx, local_id, patch_url, out_path in resume_rows
            if not is_completed_download(out_path)
        ]
        skipped_after_resume = len(resume_rows) - len(pending_rows)

        logger.log(
            "Starting run "
            f"(input={input_path}, out_dir={out_dir}, total={total}, workers={args.workers})"
        )
        logger.log(
            "Resume "
            f"(already_downloaded={existing_completed}/{total}, "
            f"next_incomplete=[{start_idx}/{total}] {start_local_id}, "
            f"pending_now={len(pending_rows)}, skipped_existing_after_resume={skipped_after_resume})"
        )

        if not pending_rows:
            logger.log(
                f"Done. success={existing_completed} failed=0 total={total} (nothing pending after resume)"
            )
            return 0

        ok_new = 0
        fail = 0
        solver_cm: PlaywrightChallengeSolver | None = None
        solver: PlaywrightChallengeSolver | None = None
        playwright_unavailable: str | None = None

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [
                    executor.submit(
                        download_one_http,
                        idx,
                        total,
                        local_id,
                        patch_url,
                        out_dir,
                        args.timeout,
                        args.max_retries,
                        args.retry_base_s,
                        args.retry_max_s,
                        args.sleep,
                    )
                    for idx, local_id, patch_url in pending_rows
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:
                        fail += 1
                        logger.log(f"Worker exception: {exc}", error=True)
                        continue

                    if result.status == "ok":
                        ok_new += 1
                        logger.log(result.message)
                        continue

                    if result.status == "err":
                        fail += 1
                        logger.log(result.message, error=True)
                        continue

                    # Challenge path: handle immediately with Playwright.
                    logger.log(result.message)
                    assert result.challenge_url is not None
                    assert result.manual_patch_url is not None

                    if playwright_unavailable is not None:
                        fail += 1
                        logger.log(
                            f"[{result.idx}/{result.total}] ERR {result.local_id} -> "
                            f"Playwright unavailable earlier: {playwright_unavailable}",
                            error=True,
                        )
                        continue

                    if solver is None:
                        try:
                            solver_cm = PlaywrightChallengeSolver(
                                browser_name=args.playwright_browser,
                                headful=args.playwright_headful,
                                timeout_ms=args.playwright_timeout_ms,
                                max_wait_s=args.playwright_max_wait_s,
                            )
                            solver = solver_cm.__enter__()
                        except Exception as exc:
                            playwright_unavailable = str(exc)
                            fail += 1
                            logger.log(
                                f"[{result.idx}/{result.total}] ERR {result.local_id} -> "
                                f"Playwright fallback unavailable: {exc}",
                                error=True,
                            )
                            continue

                    try:
                        diff_bytes = solver.fetch_patch_after_challenge(
                            challenge_url=result.challenge_url,
                            patch_url=result.manual_patch_url,
                        )
                        result.out_path.write_bytes(diff_bytes)
                        ok_new += 1
                        logger.log(
                            f"[{result.idx}/{result.total}] OK {result.local_id} -> "
                            f"{result.out_path} ({result.manual_patch_url})"
                        )
                    except Exception as exc:
                        fail += 1
                        logger.log(
                            f"[{result.idx}/{result.total}] ERR {result.local_id} -> {exc}",
                            error=True,
                        )
        finally:
            if solver_cm is not None:
                solver_cm.__exit__(None, None, None)

        success_total = existing_completed + ok_new
        logger.log(
            f"Done. success={success_total} failed={fail} total={total} "
            f"(existing={existing_completed}, downloaded_now={ok_new})"
        )
        return 0 if fail == 0 else 1
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
