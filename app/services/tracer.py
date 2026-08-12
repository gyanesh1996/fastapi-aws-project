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
from urllib.parse import urljoin, urlsplit

from app.core.config import settings
from app.models.schemas import Destination, Hop, Platform, TraceResult
from app.services import detect, extract
from app.services.fetcher import BLOCK_STATUS, TIER_LADDER, FetchResult, Fetcher
from app.services.profiles import (
    COUNTRY_PROFILES,
    USER_AGENTS,
    build_headers,
    normalize_country,
    normalize_device,
)

REDIRECT_STATUS = {301, 302, 303, 307, 308}


def _full_html(result) -> str:
    """Full (uncapped) response body for deep destination scanning."""
    if result.content:
        try:
            return result.content.decode("utf-8", "replace")
        except Exception:
            return result.text
    return result.text


def _same_url(a: str, b: str) -> bool:
    """True if two URLs point to the same resource (ignoring fragment)."""
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.netloc.lower(), pa.path.rstrip("/"), pa.query) == (
        pb.netloc.lower(),
        pb.path.rstrip("/"),
        pb.query,
    )


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
        self.final_page_title: Optional[str] = None

    async def _fetch_with_escalation(
        self, url: str, *, render: bool = False, screenshot: bool = False
    ) -> FetchResult:
        """Fetch a URL, escalating the proxy tier if the egress looks blocked."""
        if not self.fetcher.enabled:
            return await self.fetcher.fetch(url, headers=self.headers, render=render, screenshot=screenshot)

        tiers = _tier_sequence(self.tier)
        if (render or screenshot) and self.tier == "auto":
            # Datacenter render is unreliable/blocked on protected ad domains;
            # go straight to residential and escalate to ultra if needed.
            tiers = ["premium", "ultra"]
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
                # App-scheme deep links (market:// / intent:// / itms-apps://) are
                # terminal store destinations, not fetchable URLs. Adjust and other
                # MMPs return these to a mobile client.
                if detect.is_app_scheme(next_url):
                    store_url = detect.to_store_https(next_url) or next_url
                    hops.append(
                        await self._terminal_store_hop(
                            len(hops) + 1, store_url,
                            "Android/iOS app-scheme redirect resolved to the store.",
                        )
                    )
                    break
                current_url = urljoin(current_url, next_url)
                continue

            # Stalled on a 200 with no HTTP/meta/JS redirect we could parse. Try the
            # cheap options before the expensive headless render.
            if result.status_code == 200 and not detect.is_store_url(current_url):
                # (a) Destination embedded in this MMP link's own query (AppsFlyer
                #     af_android_url / Adjust redirect_*) or in the page source.
                embedded = detect.destination_from_query(
                    current_url, self.device
                ) or detect.find_destination(_full_html(result), self.device)
                if embedded:
                    hops[-1].redirect_type = "javascript"
                    hops.append(
                        await self._terminal_store_hop(
                            len(hops) + 1, embedded,
                            "Store destination extracted from the page source.",
                        )
                    )
                    break

                # (b) MMP fingerprint pages usually serve a clean 302 to a neutral
                # (non-mobile) User-Agent. Cheap and reliable for Adjust/AppsFlyer.
                if self.fetcher.enabled and detect.identify_platform(current_url):
                    stalled_hop = hops[-1]
                    probe = await self._bot_ua_probe(current_url, hops)
                    if probe:
                        is_store, purl = probe
                        stalled_hop.redirect_type = "javascript"
                        if is_store:
                            hops.append(
                                await self._terminal_store_hop(
                                    len(hops) + 1, purl,
                                    "Store destination from a clean redirect.",
                                )
                            )
                            break
                        if purl not in visited:
                            current_url = purl
                            continue

                # (c) Last resort: headless render (residential) + sa-final-url.
                if settings.ENABLE_RENDER_ESCALATION and self.fetcher.enabled and not rendered_once:
                    rendered_once = True
                    hops[-1].redirect_type = "javascript"
                    new_hops = await self._resolve_via_render(step, current_url)
                    hops.extend(new_hops)
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

    async def _terminal_store_hop(self, step: int, store_url: str, note: str) -> Hop:
        """Build the final store hop, confirming it (status + app title) when possible."""
        status: Optional[int] = None
        title: Optional[str] = None
        # Fetch a clean store URL (no tracking referrer) for a reliable title.
        dest = detect.parse_destination(store_url) or {}
        if dest.get("package"):
            fetch_url = f"https://play.google.com/store/apps/details?id={dest['package']}&hl=en"
        elif dest.get("app_id"):
            fetch_url = f"https://apps.apple.com/app/id{dest['app_id']}"
        else:
            fetch_url = store_url
        try:
            # Desktop UA so the store returns its https page (not a market:// link).
            res = await self.fetcher.fetch(
                fetch_url,
                headers=build_headers("desktop", self.country),
                tier="basic",
            )
            if res.ok_transport:
                status = res.status_code
                if res.status_code == 200:
                    # og:title can sit ~1MB into a Play page, past the text cap, so
                    # extract from the full response bytes.
                    html = res.text
                    if res.content:
                        try:
                            html = res.content.decode("utf-8", "replace")
                        except Exception:
                            html = res.text
                    title = extract.page_title(html)
        except Exception:
            pass
        if title:
            title = (
                title.replace(" - Apps on Google Play", "")
                .replace(" – Apps on Google Play", "")
                .replace(" on the App Store", "")
                .strip()
            )
            self.final_page_title = title
        return Hop(
            step=step,
            url=store_url,
            status_code=status,
            reason=_reason(status),
            redirect_type="final",
            platform=self._platform(store_url),
            rendered=False,
            note=note,
        )

    async def _bot_ua_probe(self, url: str, hops: List[Hop]) -> Optional[Tuple[bool, str]]:
        """Re-fetch an MMP interstitial with a neutral UA to elicit a clean 302.

        Appends the probe hop. Returns (is_store, url): is_store True means url is a
        resolved store link; False means it's an http(s) URL to keep following.
        Returns None if the probe found nothing new.
        """
        # A neutral desktop UA makes MMPs return the clean https store 302 instead
        # of the mobile market:// deep link or a fingerprint interstitial.
        res = await self.fetcher.fetch(
            url,
            headers={"User-Agent": USER_AGENTS["desktop"], "Accept": "text/html,*/*;q=0.8"},
            tier="basic",
        )
        if not res.ok_transport:
            return None

        location = res.headers.get("location") if res.status_code in REDIRECT_STATUS else None
        embedded = detect.find_destination(res.text) if res.status_code == 200 else None
        resolved: Optional[Tuple[bool, str]] = None

        if location and detect.is_app_scheme(location):
            resolved = (True, detect.to_store_https(location) or location)
        elif location and location.startswith(("http://", "https://")):
            resolved = (detect.is_store_url(location), location)
        elif embedded:
            resolved = (True, embedded)

        if not resolved:
            return None

        hops.append(
            Hop(
                step=len(hops) + 1,
                url=url,
                status_code=res.status_code,
                reason=_reason(res.status_code),
                redirect_type="http_redirect" if location else "javascript",
                location=location,
                platform=self._platform(url),
                tier_used=res.tier_used,
                elapsed_ms=res.elapsed_ms,
                note="Re-fetched with a neutral User-Agent to bypass the JS fingerprint page.",
            )
        )
        return resolved

    async def _resolve_via_render(self, step: int, url: str) -> List[Hop]:
        """Headless-render a stalled interstitial, follow the JS/SDK redirect chain,
        and record the rendered hop plus the final destination.

        ScraperAPI's browser follows the whole client-side chain in one shot and
        reports where it landed via the ``sa-final-url`` response header.
        """
        new_hops: List[Hop] = []
        result = await self._fetch_with_escalation(url, render=True)

        failed = (not result.ok_transport) or (result.status_code in BLOCK_STATUS)
        note = "Headless-render pass to follow the client-side (JavaScript/SDK) redirect."
        if failed:
            reason = result.error or f"status {result.status_code}"
            note += f" Render failed ({reason}); try tier=ultra or check ScraperAPI credits."
        new_hops.append(
            Hop(
                step=step,
                url=url,
                status_code=result.status_code or None,
                reason=_reason(result.status_code),
                redirect_type="rendered",
                platform=self._platform(url),
                tier_used=result.tier_used,
                rendered=True,
                elapsed_ms=result.elapsed_ms,
                note=note,
            )
        )
        if failed:
            return new_hops

        # Where did the browser end up? sa-final-url is authoritative for https,
        # but it can never hold market:// / intent:// (Chromium can't navigate those
        # schemes), so scan the rendered body for a store link when sa-final-url is
        # missing or still an interstitial.
        final_url = result.extra.get("final_url")
        if not final_url or not detect.is_store_url(final_url):
            embedded = detect.find_destination(_full_html(result), self.device)
            if embedded:
                final_url = embedded
        if not final_url:
            found = extract.find_next_url(
                base_url=url,
                text=result.text,
                content_type=result.headers.get("content-type", ""),
                refresh_header=result.headers.get("refresh"),
            )
            final_url = found[0] if found else None

        if not final_url or _same_url(final_url, url):
            new_hops[-1].note += " No further destination detected in the rendered page."
            return new_hops

        self.final_page_title = extract.page_title(result.text)
        new_hops.append(
            Hop(
                step=step + 1,
                url=final_url,
                status_code=result.status_code,
                reason=_reason(result.status_code),
                redirect_type="final",
                platform=self._platform(final_url),
                server=result.headers.get("server"),
                content_type=(result.headers.get("content-type", "").split(";")[0] or None),
                tier_used=result.tier_used,
                rendered=True,
                elapsed_ms=result.elapsed_ms,
                note="Final landing page resolved by the headless browser (sa-final-url).",
            )
        )
        return new_hops

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
            if self.final_page_title:
                destination.app_name = self.final_page_title
        elif final_hop and self.final_page_title:
            # Non-store landing (e.g. an offerwall page): surface the app/page title.
            destination = Destination(
                store=(final_platform.name if final_platform else None),
                app_name=self.final_page_title,
                url=final_url,
            )

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
