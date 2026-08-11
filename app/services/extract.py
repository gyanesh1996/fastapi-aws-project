"""Find the "next URL" inside a non-redirect (HTTP 200) response body.

Ad/tracking chains don't only use HTTP 3xx. They also bounce through:
  * ``<meta http-equiv="refresh" content="0;url=...">``
  * a ``Refresh:`` response header
  * JavaScript: ``window.location = ...``, ``location.replace(...)`` etc.
  * JSON click responses: ``{"clickUrl": "..."}``
This module extracts those so the tracer can keep following the chain.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

# <meta http-equiv="refresh" content="2; url=https://...">
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*"""
    r"""content\s*=\s*["']?\s*\d+\s*;\s*url\s*=\s*([^"'>\s]+)""",
    re.IGNORECASE,
)

# Refresh: 0; url=... (response header form)
_REFRESH_HEADER_RE = re.compile(r"\d+\s*;\s*url\s*=\s*(\S+)", re.IGNORECASE)

# JavaScript location assignments / replacements. Captures the quoted URL.
_JS_REDIRECT_RES = [
    re.compile(r"""(?:window\.|top\.|self\.|document\.)?location\s*\.\s*replace\s*\(\s*["']([^"']+)["']""", re.I),
    re.compile(r"""(?:window\.|top\.|self\.|document\.)?location\s*\.\s*assign\s*\(\s*["']([^"']+)["']""", re.I),
    re.compile(r"""(?:window\.|top\.|self\.|document\.)?location\s*\.\s*href\s*=\s*["']([^"']+)["']""", re.I),
    re.compile(r"""(?:window\.|top\.|self\.|document\.)?location\s*=\s*["']([^"']+)["']""", re.I),
]

# Common "next url" keys in JSON click responses, strongest signal first.
_JSON_URL_KEYS = ("clickUrl", "click_url", "redirectUrl", "redirect", "location", "url", "target", "destination", "dest")


def _looks_like_url(candidate: str) -> bool:
    if not candidate:
        return False
    c = candidate.strip().strip("\"'")
    return c.startswith(("http://", "https://", "//", "/"))


def _clean(candidate: str) -> str:
    return candidate.strip().strip("\"'").replace("&amp;", "&")


def _norm(url: str) -> tuple:
    """Normalized identity of a URL for self-reference comparison."""
    parts = urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query)


def _accept(base_url: str, candidate: str) -> Optional[str]:
    """Return the absolute next URL, or None if invalid or self-referential."""
    if not _looks_like_url(candidate):
        return None
    absolute = urljoin(base_url, _clean(candidate))
    if not absolute.startswith(("http://", "https://")):
        return None
    if _norm(absolute) == _norm(base_url):
        return None
    return absolute


def _json_candidates(text: str, content_type: str) -> List[str]:
    is_jsonish = "json" in (content_type or "").lower() or text.lstrip().startswith(("{", "["))
    if not is_jsonish:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    out: List[str] = []
    if isinstance(data, dict):
        for key in _JSON_URL_KEYS:
            value = data.get(key)
            if isinstance(value, str) and _looks_like_url(value):
                out.append(value)
        for value in data.values():  # one level down: {"data": {"clickUrl": ...}}
            if isinstance(value, dict):
                for key in _JSON_URL_KEYS:
                    inner = value.get(key)
                    if isinstance(inner, str) and _looks_like_url(inner):
                        out.append(inner)
    return out


def from_meta_refresh(html: str) -> Optional[str]:
    match = _META_REFRESH_RE.search(html or "")
    return match.group(1) if match else None


def from_refresh_header(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    match = _REFRESH_HEADER_RE.search(header_value)
    return match.group(1) if match else None


def from_javascript(html: str) -> Optional[str]:
    for pattern in _JS_REDIRECT_RES:
        match = pattern.search(html or "")
        if match:
            return match.group(1)
    return None


def find_next_url(
    *, base_url: str, text: str, content_type: str, refresh_header: Optional[str]
) -> Optional[Tuple[str, str]]:
    """Return (absolute_next_url, redirect_type) or None.

    redirect_type is one of: json_clickurl | meta_refresh | javascript.
    Self-referential candidates (a page pointing to itself) are ignored.
    """
    for candidate in _json_candidates(text, content_type):
        absolute = _accept(base_url, candidate)
        if absolute:
            return absolute, "json_clickurl"

    for raw, rtype in (
        (from_refresh_header(refresh_header), "meta_refresh"),
        (from_meta_refresh(text), "meta_refresh"),
        (from_javascript(text), "javascript"),
    ):
        if raw:
            absolute = _accept(base_url, raw)
            if absolute:
                return absolute, rtype

    return None
