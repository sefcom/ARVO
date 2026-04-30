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
import importlib.util
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

globalStrReplace = {
    "git://anongit.freedesktop.org/xorg/lib/libXext": "https://gitlab.freedesktop.org/xorg/lib/libxext.git",
    "git://anongit.freedesktop.org/mesa/drm": "https://gitlab.freedesktop.org/mesa/libdrm.git",
    "git://anongit.freedesktop.org/git/xorg/lib/libXfixes": "https://gitlab.freedesktop.org/xorg/lib/libxfixes.git",
    "https://bitbucket.org/multicoreware/x265_git/src/stable/": "https://bitbucket.org/multicoreware/x265_git.git",
    "http://download.icu-project.org/files/icu4c/59.1/icu4c-59_1-src.tgz": "https://github.com/unicode-org/icu/releases/download/release-59-1/icu4c-59_1-src.tgz",
    "git://git.gnome.org/libxml2": "https://gitlab.gnome.org/GNOME/libxml2.git",
    "svn://vcs.exim.org/pcre2/code/trunk pcre2": "https://github.com/PCRE2Project/pcre2",
    "https://git.savannah.nongnu.org/r/freetype/freetype2": "https://github.com/freetype/freetype2",
    "https://git.savannah.gnu.org/git/freetype/freetype2.git": "https://github.com/freetype/freetype2",
    "https://git.sv.nongnu.org/r/freetype/freetype2.git": "https://github.com/freetype/freetype2",
    "git://git.sv.nongnu.org/freetype/freetype2.git": "https://github.com/freetype/freetype2",
    "https://gitlab.freedesktop.org/freetype/freetype.git": "https://github.com/freetype/freetype",
    "ftp://ftp.unidata.ucar.edu/pub/netcdf/netcdf-4.4.1.1.tar.gz": "http://ppmcore.mpi-cbg.de/upload/netcdf-4.4.1.1.tar.gz",
    "https://github.com/01org/libva": "https://github.com/intel/libva.git",
    "https://github.com/intel/libva\n": "https://github.com/intel/libva.git\n",
    "http://www.zlib.net/zlib-1.2.11.tar.gz": "https://www.zlib.net/fossils/zlib-1.2.11.tar.gz",
    "https://jannau.net/dav1d_fuzzer_seed_corpus.zip": "https://download.videolan.org/pub/videolan/testing/contrib/dav1d/dav1d_fuzzer_seed_corpus.zip",
    "git://git.xiph.org/ogg.git": "https://gitlab.xiph.org/xiph/ogg.git",
    "https://github.com/xiph/ogg.git": "https://gitlab.xiph.org/xiph/ogg.git",
    "git://git.xiph.org/opus.git": "https://gitlab.xiph.org/xiph/opus.git",
    "git://git.xiph.org/theora.git": "https://gitlab.xiph.org/xiph/theora.git",
    "git://git.xiph.org/vorbis.git": "https://gitlab.xiph.org/xiph/vorbis.git",
    "http://svn.xiph.org/trunk/ogg": "https://gitlab.xiph.org/xiph/ogg.git",
    "git://git.videolan.org/git/x264.git": "https://code.videolan.org/videolan/x264.git",
    "http://lcamtuf.coredump.cx/afl/demo/afl_testcases.tgz": "https://lcamtuf.coredump.cx/afl/demo/afl_testcases.tgz",
    "https://downloads.apache.org/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.zip": "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.6.3/apache-maven-3.6.3-bin.zip",
    "https://downloads.apache.org/maven/maven-3/3.8.6/binaries/apache-maven-3.8.6-bin.zip": "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.8.6/apache-maven-3.8.6-bin.zip",
    "https://downloads.apache.org/maven/maven-3/3.8.5/binaries/apache-maven-3.8.5-bin.zip": "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.8.5/apache-maven-3.8.5-bin.zip",
    "https://dlcdn.apache.org/maven/maven-3/3.8.6/binaries/apache-maven-3.8.6-bin.zip": "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.8.6/apache-maven-3.8.6-bin.zip",
    "https://dlcdn.apache.org/maven/maven-3/3.8.5/binaries/apache-maven-3.8.5-bin.zip": "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.8.5/apache-maven-3.8.5-bin.zip",
    "https://opus-codec.org/static/testvectors/opus_testvectors.tar.gz": "http://opus-codec.org/static/testvectors/opus_testvectors.tar.gz",
    "https://anongit.freedesktop.org/git/harfbuzz.git": "https://github.com/harfbuzz/harfbuzz.git",
    "git://anongit.kde.org/extra-cmake-modules": "https://invent.kde.org/frameworks/extra-cmake-modules.git",
    "git://anongit.kde.org/kimageformats": "https://invent.kde.org/frameworks/kimageformats.git",
    "git://anongit.kde.org/karchive": "https://invent.kde.org/frameworks/karchive.git",
    "git://git.savannah.gnu.org/gnulib.git": "https://github.com/coreutils/gnulib.git",
    "http://llvm.org/svn/llvm-project/llvm/trunk": "https://github.com/llvm/llvm-project.git",
    "svn://vcs.exim.org/pcre/code/trunk": "https://github.com/PhilipHazel/pcre2",
    "https://github.com/cmeister2/libssh2.git": "https://github.com/libssh2/libssh2.git",
    "git://git.code.sf.net/p/matio/matio": "https://github.com/tbeu/matio.git",
    "https://github.com/cmeister2/aspell.git": "https://github.com/gnuaspell/aspell.git",
    "https://github.com/erikd/libsndfile.git": "https://github.com/libsndfile/libsndfile.git",
    "https://anongit.freedesktop.org/git/poppler/poppler.git": "https://gitlab.freedesktop.org/poppler/poppler.git",
    "https://gitlab.freedesktop.org/ceyhunalp/poppler.git": "https://gitlab.freedesktop.org/poppler/poppler.git",
    "https://github.com/guidovranken/cryptofuzz": "https://github.com/MozillaSecurity/cryptofuzz.git",
    "git://anongit.freedesktop.org/libreoffice/core": "https://git.libreoffice.org/core",
    "https://git.qemu.org/git/qemu.git": "https://gitlab.com/qemu-project/qemu.git",
    "https://gnunet.org/git": "https://git.gnunet.org",
    "curl http://": "curl -L http://",
    "curl https://": "curl -L https://",
    "curl ftp://": "curl -L ftp://",
    "&& curl http": "&& curl -L http",
    "&& curl ftp": "&& curl -L ftp",
    " --depth 1": "",
    " --depth=1": "",
    " --depth ": " --jobs ",
    " --recursive ": " ",
}


def load_check_trans_table():
    here = Path(__file__).resolve().parent
    candidates = [
        here / "ARVO" / "arvo" / "transform.py",
        here / "arvo" / "transform.py",
    ]
    for module_path in candidates:
        if not module_path.exists():
            continue
        spec = importlib.util.spec_from_file_location(
            "arvo_transform_local", module_path
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check = getattr(module, "check_trans_table", None)
        if callable(check):
            return check
    raise SystemExit(
        "Error: failed to load check_trans_table from ARVO/arvo/transform.py."
    )


check_trans_table = load_check_trans_table()


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
    parser.add_argument(
        "--disable-playwright-fallback",
        action="store_true",
        help="Disable Playwright fallback when JS/CAPTCHA challenges are detected.",
    )
    parser.add_argument(
        "--playwright-browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Browser engine for Playwright fallback (default: chromium).",
    )
    parser.add_argument(
        "--playwright-headful",
        action="store_true",
        help="Run Playwright fallback in a visible browser window.",
    )
    parser.add_argument(
        "--playwright-timeout-ms",
        type=int,
        default=30000,
        help="Playwright navigation/request timeout in ms (default: 30000).",
    )
    parser.add_argument(
        "--playwright-max-wait-s",
        type=float,
        default=60.0,
        help="Max wait per challenge URL during Playwright fallback (default: 60).",
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


class JSChallengeRequired(RuntimeError):
    def __init__(self, reason: str, challenge_url: str, manual_patch_url: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.challenge_url = challenge_url
        self.manual_patch_url = manual_patch_url


def sanitize_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "entry"


def output_path_for(local_id: str, patch_url: str, out_dir: Path) -> Path:
    url_hash = hashlib.sha1(patch_url.encode("utf-8")).hexdigest()[:10]
    return out_dir / f"{sanitize_name(local_id)}_{url_hash}.diff"


def is_completed_download(path: Path) -> bool:
    return path.exists() and path.is_file() and path.stat().st_size > 0


def extract_commit_hash(url: str) -> str | None:
    match = re.search(r"([0-9a-fA-F]{40})", urllib.parse.unquote(url))
    if not match:
        return None
    return match.group(1).lower()


def guess_repo_names_from_url(url: str) -> list[str]:
    parsed = urllib.parse.urlparse(url)
    segments = [urllib.parse.unquote(s) for s in parsed.path.split("/") if s]
    names: list[str] = []

    def add_name(raw: str) -> None:
        candidate = raw.strip()
        if not candidate:
            return
        candidate = re.sub(r"[0-9a-fA-F]{40}$", "", candidate)
        if candidate.endswith(".git"):
            candidate = candidate[:-4]
        if candidate in {"-", "+", "commit", "patch", "rev", "raw-rev", "gitweb"}:
            return
        if candidate and candidate not in names:
            names.append(candidate)

    for marker in ("commit", "+", "rev", "raw-rev"):
        if marker in segments:
            idx = segments.index(marker)
            if idx > 0:
                add_name(segments[idx - 1])
            if marker == "commit" and idx > 1 and segments[idx - 1] == "-":
                add_name(segments[idx - 2])

    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    for repo_hint in params.get("p", []):
        add_name(repo_hint.split("/")[-1])

    for segment in reversed(segments):
        add_name(segment)
    return names


def candidate_item_names(local_id: str, item_name_hint: str, url: str) -> list[str]:
    names: list[str] = []

    def add_item_name(raw: str) -> None:
        value = raw.strip()
        if not value:
            return
        if not value.startswith("/src/"):
            value = f"/src/{value}"
        if value not in names:
            names.append(value)

    if item_name_hint:
        add_item_name(item_name_hint)
    if local_id:
        add_item_name(local_id)
    for repo_name in guess_repo_names_from_url(url):
        add_item_name(repo_name)
        add_item_name(repo_name.lower())
    return names


def build_patch_url_from_repo_base(
    base_url: str, commit_hash: str, repo_type: str
) -> str:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    path_no_git = path[:-4] if path.endswith(".git") else path
    scheme = "https"

    if "googlesource.com" in host:
        new_path = f"{path}/+/{commit_hash}^!/"
        return urllib.parse.urlunparse(
            parsed._replace(scheme=scheme, path=new_path, query="")
        )

    if (
        "cgit." in host
        or host in {"sourceware.org", "git.savannah.gnu.org", "git.libssh.org", "w1.fi"}
        or "git.ffmpeg.org" in host
    ):
        new_path = f"{path}/patch"
        new_query = urllib.parse.urlencode({"id": commit_hash})
        return urllib.parse.urlunparse(
            parsed._replace(scheme=scheme, path=new_path, query=new_query)
        )

    if "github.com" in host:
        new_path = f"{path_no_git}/commit/{commit_hash}"
        return urllib.parse.urlunparse(
            parsed._replace(scheme=scheme, path=new_path, query="")
        )

    if "hg.nginx.org" in host:
        new_path = f"{path_no_git}/raw-rev/{commit_hash}"
        return urllib.parse.urlunparse(
            parsed._replace(scheme=scheme, path=new_path, query="")
        )

    if (
        repo_type == "hg"
        or "gitlab" in host
        or "heptapod.net" in host
        or host in {"invent.kde.org", "code.videolan.org"}
    ):
        new_path = f"{path_no_git}/-/commit/{commit_hash}"
        return urllib.parse.urlunparse(
            parsed._replace(scheme=scheme, path=new_path, query="")
        )

    return urllib.parse.urlunparse(parsed._replace(scheme=scheme))


def transform_patch_url_with_arvo(local_id: str, item_name_hint: str, url: str) -> str:
    commit_hash = extract_commit_hash(url)
    for item_name in candidate_item_names(local_id, item_name_hint, url):
        _, mapped_url, mapped_type = check_trans_table(item_name, url, "git")
        if not mapped_url:
            continue
        if mapped_url == url:
            continue
        if commit_hash:
            return build_patch_url_from_repo_base(
                mapped_url, commit_hash, mapped_type or "git"
            )
        return mapped_url
    return url


def candidate_urls(
    url: str, local_id: str, item_name_hint: str
) -> list[tuple[str, bool]]:
    """Return (candidate_url, is_googlesource_base64_diff)."""
    out: list[tuple[str, bool]] = []

    def append_unique(u: str, is_b64: bool = False) -> None:
        if not any(existing == u for existing, _ in out):
            out.append((u, is_b64))

    transformed = transform_patch_url_with_arvo(local_id, item_name_hint, url)
    base_urls: list[tuple[str, bool]] = [(transformed, transformed != url)]
    if transformed != url:
        base_urls.append((url, False))

    for base_url, is_transformed in base_urls:
        parsed = urllib.parse.urlparse(base_url)
        host = parsed.netloc.lower()
        has_query = bool(parsed.query)
        path_has_suffix = parsed.path.endswith(".patch") or parsed.path.endswith(
            ".diff"
        )
        skip_generic_suffix = has_query or host == "hg.nginx.org" or path_has_suffix

        append_unique(base_url, False)

        if not is_transformed and "github.com" in host and "/commit/" in parsed.path:
            append_unique(base_url + ".patch", False)
            append_unique(base_url + ".diff", False)

        if "googlesource.com" in host and "/+/" in parsed.path:
            joiner = "&" if parsed.query else "?"
            append_unique(base_url + f"{joiner}format=TEXT", True)

        # Generic path suffix variants are only safe for path-style URLs.
        # Query-style patch endpoints (e.g., .../patch?id=...) should not become ...id=....patch.
        if not is_transformed and not skip_generic_suffix:
            append_unique(base_url + ".patch", False)
            append_unique(base_url + ".diff", False)
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


def fetch_with_playwright(
    challenge_url: str,
    patch_url: str,
    browser_name: str,
    headful: bool,
    timeout_ms: int,
    max_wait_s: float,
) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright not installed. Install with: pip install playwright && playwright install"
        ) from exc

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, browser_name)
        browser = browser_type.launch(
            headless=not headful,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            context = browser.new_context(
                ignore_https_errors=True,
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            context.set_default_timeout(timeout_ms)
            context.set_default_navigation_timeout(timeout_ms)
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = context.new_page()
            try:
                page.goto(challenge_url, wait_until="domcontentloaded")
                deadline = time.time() + max_wait_s
                while time.time() < deadline:
                    try:
                        response = page.goto(patch_url, wait_until="domcontentloaded")
                    except Exception:
                        response = None

                    if response is not None:
                        try:
                            body = response.body()
                            text = body.decode("utf-8", errors="replace")
                            if looks_like_diff(text):
                                return body
                        except Exception:
                            pass

                    try:
                        body_text = page.evaluate(
                            "() => document.body ? document.body.innerText : ''"
                        )
                    except Exception:
                        body_text = ""
                    if looks_like_diff(body_text):
                        return body_text.encode("utf-8")

                    page.wait_for_timeout(1500 + int(random.uniform(0, 600)))
                    try:
                        page.goto(challenge_url, wait_until="domcontentloaded")
                    except Exception:
                        pass
                raise RuntimeError(
                    "Playwright could not clear challenge in time. "
                    f"Try --playwright-headful and larger --playwright-max-wait-s. URL: {patch_url}"
                )
            finally:
                page.close()
                context.close()
        finally:
            browser.close()


def fetch_diff(
    local_id: str,
    item_name_hint: str,
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

    candidates = candidate_urls(url, local_id=local_id, item_name_hint=item_name_hint)
    manual_patch_url = next(
        (
            candidate
            for candidate, _ in candidates
            if candidate.endswith(".patch")
            or "/patch/" in urllib.parse.urlparse(candidate).path
            or urllib.parse.urlparse(candidate).path.endswith("/patch")
        ),
        transform_patch_url_with_arvo(local_id, item_name_hint, url),
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
                should_retry = (
                    exc.code in retryable_http_codes and attempts <= max_retries
                )
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
                errors.append(
                    f"{candidate} -> URL error: {exc.reason} (attempts={attempts})"
                )
                break

            content = maybe_decode_googlesource(body, is_b64)
            text = content.decode("utf-8", errors="replace")
            if is_anubis_challenge(text):
                raise JSChallengeRequired(
                    reason="Anubis browser challenge detected",
                    challenge_url=candidate,
                    manual_patch_url=manual_patch_url,
                )

            soft_block = detect_soft_block_reason(text)
            if soft_block is not None:
                if soft_block.lower() in manual_challenge_markers:
                    raise JSChallengeRequired(
                        reason=f"{soft_block} at {candidate}",
                        challenge_url=candidate,
                        manual_patch_url=manual_patch_url,
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
    item_name_hint: str,
    patch_url: str,
    timeout: int,
    max_retries: int,
    retry_base_s: float,
    retry_max_s: float,
    playwright_enabled: bool,
    playwright_browser: str,
    playwright_headful: bool,
    playwright_timeout_ms: int,
    playwright_max_wait_s: float,
    out_dir: Path,
    sleep_seconds: float,
) -> tuple[bool, str]:
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    out_path = output_path_for(local_id, patch_url, out_dir)
    try:
        used_url, diff_bytes = fetch_diff(
            local_id=local_id,
            item_name_hint=item_name_hint,
            url=patch_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_base_s=retry_base_s,
            retry_max_s=retry_max_s,
        )
        out_path.write_bytes(diff_bytes)
        return True, f"[{idx}/{total}] OK  {local_id} -> {out_path} (from {used_url})"
    except JSChallengeRequired as exc:
        if not playwright_enabled:
            return (
                False,
                f"[{idx}/{total}] ERR {local_id} -> browser challenge detected; "
                f"manual URL: {exc.manual_patch_url}",
            )
        try:
            diff_bytes = fetch_with_playwright(
                challenge_url=exc.challenge_url,
                patch_url=exc.manual_patch_url,
                browser_name=playwright_browser,
                headful=playwright_headful,
                timeout_ms=playwright_timeout_ms,
                max_wait_s=playwright_max_wait_s,
            )
            out_path.write_bytes(diff_bytes)
            return (
                True,
                f"[{idx}/{total}] OK  {local_id} -> {out_path} "
                f"(from {exc.manual_patch_url} via Playwright)",
            )
        except Exception as pw_exc:
            return (
                False,
                f"[{idx}/{total}] ERR {local_id} -> challenge fallback failed: {pw_exc}; "
                f"manual URL: {exc.manual_patch_url}",
            )
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
            rows = [
                (r[0].strip(), r[1].strip(), r[2].strip() if len(r) >= 3 else "")
                for r in reader
                if len(r) >= 2 and r[1].strip()
            ]

        rows = rows[args.offset :]
        if args.limit is not None:
            rows = rows[: args.limit]

        if not rows:
            logger.log("No rows to process.")
            return 0

        total = len(rows)
        indexed_rows = [
            (
                idx,
                local_id,
                patch_url,
                item_name_hint,
                output_path_for(local_id, patch_url, out_dir),
            )
            for idx, (local_id, patch_url, item_name_hint) in enumerate(rows, start=1)
        ]
        existing_completed = sum(
            1
            for _, _, _, _, out_path in indexed_rows
            if is_completed_download(out_path)
        )
        pending_rows = [
            (idx, local_id, patch_url, item_name_hint)
            for idx, local_id, patch_url, item_name_hint, out_path in indexed_rows
            if not is_completed_download(out_path)
        ]
        skipped_existing = total - len(pending_rows)

        if not pending_rows:
            logger.log(
                f"Done. success={total} failed=0 total={total} (already downloaded)"
            )
            return 0

        logger.log(
            "Resume "
            f"(already_downloaded={existing_completed}/{total}, pending_now={len(pending_rows)}, "
            f"skipped_existing={skipped_existing})"
        )

        ok_new = 0
        fail = 0

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers
        ) as executor:
            futures = [
                executor.submit(
                    download_one,
                    idx,
                    total,
                    local_id,
                    item_name_hint,
                    patch_url,
                    args.timeout,
                    args.max_retries,
                    args.retry_base_s,
                    args.retry_max_s,
                    not args.disable_playwright_fallback,
                    args.playwright_browser,
                    args.playwright_headful,
                    args.playwright_timeout_ms,
                    args.playwright_max_wait_s,
                    out_dir,
                    args.sleep,
                )
                for idx, local_id, patch_url, item_name_hint in pending_rows
            ]

            for future in concurrent.futures.as_completed(futures):
                try:
                    success, message = future.result()
                except Exception as exc:
                    fail += 1
                    logger.log(f"Worker exception: {exc}", error=True)
                    continue
                if success:
                    ok_new += 1
                    logger.log(message)
                else:
                    fail += 1
                    logger.log(message, error=True)

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
