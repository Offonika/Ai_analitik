#!/usr/bin/env python3
"""Check external documentation links without joining the blocking validators."""

from __future__ import annotations

import concurrent.futures
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL_RE = re.compile(r"https?://[^\s<>`\])]+")
SKIP_HOSTS = {
    "127.0.0.1",
    "localhost",
    "shumeiko.offonika.ru",
    "example.invalid",
    "example.1cfresh.com",
    "finance-api.wildberries.ru",
    "seller-analytics-api.wildberries.ru",
    "advert-api.wildberries.ru",
    "api-seller.ozon.ru",
}


def discover_urls() -> list[str]:
    paths = [ROOT / "README.md", ROOT / "config" / "README.md"]
    paths.extend(sorted((ROOT / "docs").rglob("*.md")))
    urls: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for match in URL_RE.findall(path.read_text(encoding="utf-8")):
            url = match.rstrip(".,;:")
            parsed = urlsplit(url)
            if parsed.hostname in SKIP_HOSTS or "<" in url or ">" in url:
                continue
            urls.add(url)
    return sorted(urls)


def check_url(url: str) -> tuple[str, str, str]:
    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=10,
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "ShumeykoDocsLinkCheck/1.0"},
        ) as client:
            response = client.head(url)
            if response.status_code in {403, 405}:
                response = client.get(url)
    except httpx.TooManyRedirects:
        return "error", url, "redirect loop"
    except httpx.TimeoutException:
        return "warning", url, "timeout"
    except httpx.HTTPError as exc:
        return "warning", url, exc.__class__.__name__

    if response.status_code in {404, 410}:
        return "error", url, f"HTTP {response.status_code}"
    if response.status_code == 429:
        return "warning", url, "HTTP 429"
    if response.status_code >= 400:
        return "warning", url, f"HTTP {response.status_code}"
    return "ok", url, f"HTTP {response.status_code}"


def main() -> int:
    urls = discover_urls()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = sorted(pool.map(check_url, urls), key=lambda item: item[1])
    errors = [item for item in results if item[0] == "error"]
    warnings = [item for item in results if item[0] == "warning"]
    for _level, url, message in errors:
        print(f"ERROR {message}: {url}")
    for _level, url, message in warnings:
        print(f"WARNING {message}: {url}")
    print(
        f"External links checked: {len(results)}, "
        f"errors: {len(errors)}, warnings: {len(warnings)}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
