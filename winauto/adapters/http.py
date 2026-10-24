"""Small HTTP helpers (standard library only) and HTML-to-text."""

from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class FetchError(Exception):
    pass


def fetch(url: str, *, timeout: float = 12, max_bytes: int = 3_000_000, data: bytes | None = None,
          headers: dict[str, str] | None = None) -> tuple[str, str]:
    """GET (or POST if data) a URL. Returns (text, final_url)."""
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8", "Accept-Encoding": "gzip",
                 **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes)
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), resp.geturl()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url} answered with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"Couldn't reach {urllib.parse.urlsplit(url).netloc or url}: {reason}") from exc


def fetch_json(url: str, **kwargs: Any) -> Any:
    text, _ = fetch(url, **kwargs)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FetchError(f"{url} didn't return JSON") from exc


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "title", "nav", "footer", "form", "iframe", "button", "aside"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """Readable text and title from an HTML page."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    # Drop menu crumbs: very short lines next to each other.
    lines = [line for line in lines if len(line) > 2]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), unescape(parser.title.strip())


def strip_tags(fragment: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()
