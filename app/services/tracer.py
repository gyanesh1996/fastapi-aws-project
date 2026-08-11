"""The redirect-tracing engine.

Follows a tracking/affiliate URL hop by hop and returns the full chain the way
AffiliTest does: every HTTP 3xx, meta-refresh, JavaScript and JSON redirect,
with the tracking platform identified at each step and the final app-store
destination extracted.

Egress goes through ScraperAPI (real residential/geo IPs) when a key is set;
otherwise it falls back to a direct connection that works for open links but
will be blocked by serious ad networks.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from app.core.config import settings
from app.models.schemas import Destination, Hop, Platform, TraceResult
from app.services import detect, extract
from app.services.fetcher import BLOCK_STATUS, TIER_LADDER, FetchResult, Fetcher
from app.services.profiles import (
    COUNTRY_PROFILES,
    build_headers,
    normalize_country,
    normalize_device,
)

REDIRECT_STATUS = {301, 302, 303, 307, 308}


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _tier_sequence(configured: str) -> List[str]:
    """Which proxy tiers to try for a hop, in order."""
    configured = (configured or "auto").lower()
    if configured == "auto":
        return list(TIER_LADDER)  # basic -> premium -> ultra on block
    if configured in TIER_LADDER:
        return [configured]
    return ["basic"]


class RedirectTracer:
    def __init__(self, device: str, country: str, tier: Optional[str] = None):
        self.device = normalize_device(device)
        self.country = normalize_country(country)
        self.tier = (tier or settings.PROXY_TIER).lower()
        self.headers = build_headers(self.device, self.country)
        self.fetcher = Fetcher(self.country, self.device)
        self.warnings: List[str] = []

    async def _fetch_with_escalation(
        self, url: str, *, render: bool = False, screenshot: bool = False
    ) -> FetchResult:
        """Fetch a URL, escalating the proxy tier if the egress looks blocked."""
        if not self.fetcher.enabled:
            return await self.fetcher.fetch(url, headers=self.headers, render=render, screenshot=screenshot)

        tiers = _tier_sequence(self.tier)
        result: Optional[FetchResult] = None
        for tier in tiers:
            result = await self.fetcher.fetch(
                url, headers=self.headers, tier=tier, render=render, screenshot=screenshot
            )
            transport_failed = not result.ok_transport
            blocked = result.status_code in BLOCK_STATUS
            if not transport_failed and not blocked:
                return result
            # Only keep climbing the ladder in auto mode.
            if self.tier != "auto":
                return result
        return result  # last attempt (best effort)

    async def trace(self, url: str, *, screenshot: bool = False) -> TraceResult:
        start_url = _normalize_url(url)
        hops: List[Hop] = []
        visited: set[str] = set()
        current_url = start_url
        rendered_once = False

        engine = "scraperapi" if self.fetcher.enabled else "direct"
        if engine == "direct":
            self.warnings.append(
                "SCRAPERAPI_KEY is not set - running in direct mode. Ad networks that "
                "block datacenter IPs will return 403. Set the key for real geo/residential egress."
            )

        egress_ip = await self._egress_ip() if self.fetcher.enabled else None

        step = 0
        while current_url and step < settings.MAX_HOPS:
            if current_url in visited:
                self.warnings.append(f"Loop detected at {current_url}; stopping.")
                break
            visited.add(current_url)
            step += 1

            result = await self._fetch_with_escalation(current_url)

            if not result.ok_transport:
                hops.append(
                    Hop(
                        step=step,
                        url=current_url,
                        status_code=None,
                        reason="Request failed",
                        redirect_type="error",
                        platform=self._platform(current_url),
                        tier_used=result.tier_used,
                        elapsed_ms=result.elapsed_ms,
                        note=result.error,
                    )
                )
                break

            next_url, redirect_type, hop = self._build_hop(step, current_url, result)
            hops.append(hop)

            # Terminal: reached an app store, or nothing more to follow.
            if detect.is_store_url(current_url):
                hop.redirect_type = "final"
                next_url = None

            if next_url:
                current_url = urljoin(current_url, next_url)
                continue

            # No obvious next URL. If we're stalled on a 200 HTML page that isn't
            # a store, try one headless-render pass to resolve JS/SDK redirects.
            if (
                settings.ENABLE_RENDER_ESCALATION
                and self.fetcher.enabled
                and not rendered_once
                and result.status_code == 200
                and not detect.is_store_url(current_url)
            ):
                rendered_once = True
                resolved = await self._render_resolve(step, current_url)
                if resolved is not None:
                    resolved_url, render_hop = resolved
                    hops.append(render_hop)
                    if resolved_url and resolved_url not in visited:
                        current_url = resolved_url
                        continue
            break

        return self._finalize(start_url, hops, engine, egress_ip, screenshot)

    def _build_hop(
        self, step: int, url: str, result: FetchResult
    ) -> Tuple[Optional[str], str, Hop]:
        status = result.status_code
        content_type = result.headers.get("content-type", "")
        server = result.headers.get("server")
        platform = self._platform(url)
        next_url: Optional[str] = None
        redirect_type = "final"
        location = None

        if status in REDIRECT_STATUS:
            location = result.headers.get("location")
            if location:
                next_url = location
                redirect_type = "http_redirect"
        else:
            found = extract.find_next_url(
                base_url=url,
                text=result.text,
                content_type=content_type,
                refresh_header=result.headers.get("refresh"),
            )
            if found:
                next_url, redirect_type = found

        hop = Hop(
            step=step,
            url=url,
            status_code=status,
            reason=_reason(status),
            redirect_type=redirect_type,
            location=location,
            platform=platform,
            server=server,
            content_type=content_type.split(";")[0] or None,
            tier_used=result.tier_used,
            rendered=result.rendered,
            elapsed_ms=result.elapsed_ms,
            body_snippet=_snippet(result.text, content_type),
        )
        return next_url, redirect_type, hop

    async def _render_resolve(self, step: int, url: str) -> Optional[Tuple[Optional[str], Hop]]:
        """Re-fetch a stalled hop with JS rendering to find the real destination."""
        result = await self._fetch_with_escalation(url, render=True)
        if not result.ok_transport:
            return None

        store_links = detect.find_store_links(result.text)
        # Also re-run the standard extractors on the rendered HTML.
        resolved = store_links[0] if store_links else None
        if not resolved:
            found = extract.find_next_url(
                base_url=url,
                text=result.text,
                content_type=result.headers.get("content-type", ""),
                refresh_header=result.headers.get("refresh"),
            )
            resolved = found[0] if found else None

        hop = Hop(
            step=step,
            url=url,
            status_code=result.status_code,
            reason=_reason(result.status_code),
            redirect_type="rendered",
            platform=self._platform(url),
            server=result.headers.get("server"),
            content_type=(result.headers.get("content-type", "").split(";")[0] or None),
            tier_used=result.tier_used,
            rendered=True,
            elapsed_ms=result.elapsed_ms,
            note="Headless-render pass to resolve JavaScript/SDK redirect."
            + ("" if resolved else " No further destination found in rendered page."),
        )
        return (urljoin(url, resolved) if resolved else None), hop

    async def _egress_ip(self) -> Optional[str]:
        """Best-effort: report the real proxy exit IP for the chosen country."""
        try:
            result = await self.fetcher.fetch(
                "https://httpbin.org/ip", headers=self.headers, tier="basic", timeout=25.0
            )
            if result.ok_transport and result.text:
                import json

                data = json.loads(result.text)
                return data.get("origin")
        except Exception:
            return None
        return None

    def _platform(self, url: str) -> Optional[Platform]:
        info = detect.identify_platform(url)
        return Platform(**info) if info else None

    def _finalize(
        self,
        start_url: str,
        hops: List[Hop],
        engine: str,
        egress_ip: Optional[str],
        screenshot_requested: bool,
    ) -> TraceResult:
        final_hop = hops[-1] if hops else None
        final_url = final_hop.url if final_hop else start_url
        final_platform = final_hop.platform if final_hop else None

        destination = None
        dest_raw = detect.parse_destination(final_url) if final_hop else None
        if dest_raw:
            destination = Destination(**dest_raw)

        country_label = COUNTRY_PROFILES[self.country]["label"]
        # total redirects = number of transitions between hops.
        total_redirects = max(len(hops) - 1, 0)

        egress_note = None
        if engine == "scraperapi":
            tier_label = {"auto": "auto (datacenter→residential)", "basic": "datacenter",
                          "premium": "residential", "ultra": "ultra-premium residential"}.get(self.tier, self.tier)
            egress_note = f"ScraperAPI {tier_label} proxy · {country_label}"

        result = TraceResult(
            initial_url=start_url,
            device=self.device,
            country=self.country,
            country_label=country_label,
            engine=engine,
            tier=self.tier,
            egress_ip=egress_ip,
            egress_note=egress_note,
            total_redirects=total_redirects,
            final_url=final_url,
            final_status=final_hop.status_code if final_hop else None,
            final_platform=final_platform,
            destination=destination,
            hops=hops,
            warnings=self.warnings,
            meta={"hop_count": len(hops), "max_hops": settings.MAX_HOPS},
        )
        return result

    async def capture_screenshot(self, url: str) -> Optional[str]:
        """Return a data: URL PNG screenshot of the given page, or None."""
        if not self.fetcher.enabled:
            return None
        result = await self._fetch_with_escalation(url, screenshot=True)
        if result.ok_transport and result.content and result.status_code == 200:
            import base64

            b64 = base64.b64encode(result.content).decode("ascii")
            return f"data:image/png;base64,{b64}"
        return None


def _reason(status: Optional[int]) -> str:
    reasons = {
        200: "OK", 201: "Created", 204: "No Content",
        301: "Moved Permanently", 302: "Found", 303: "See Other",
        307: "Temporary Redirect", 308: "Permanent Redirect",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 405: "Method Not Allowed", 410: "Gone",
        429: "Too Many Requests", 500: "Internal Server Error",
        502: "Bad Gateway", 503: "Service Unavailable", 504: "Gateway Timeout",
    }
    if status is None:
        return "No response"
    return reasons.get(status, "")


def _snippet(text: str, content_type: str) -> Optional[str]:
    if not text:
        return None
    ct = (content_type or "").lower()
    # Keep small JSON/text bodies; skip large HTML pages to keep payload lean.
    if "json" in ct or ("html" not in ct and len(text) < 1500):
        return text[: settings.BODY_SNIPPET_LIMIT]
    return None


async def trace_url(
    url: str,
    *,
    device: str = "desktop",
    country: str = "US",
    tier: Optional[str] = None,
    screenshot: bool = False,
) -> TraceResult:
    tracer = RedirectTracer(device=device, country=country, tier=tier)
    result = await tracer.trace(url, screenshot=screenshot)
    if screenshot and result.final_url:
        result.screenshot = await tracer.capture_screenshot(result.final_url)
    return result
