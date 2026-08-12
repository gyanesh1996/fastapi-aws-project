"""Request layer.

Wraps a single HTTP request so the tracer doesn't care whether it goes out
directly or through ScraperAPI. In proxy mode we pass ScraperAPI options in the
proxy username (``scraperapi.<opt>=<val>....:APIKEY@host:port``) and always keep
``follow_redirect=false`` so *we* see each 3xx + Location and build the chain
ourselves — ScraperAPI would otherwise collapse the whole chain into the final
page.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.services.profiles import SCRAPERAPI_DEVICE_TYPE

# Ordered escalation ladder for the "auto" tier. Each entry is (label, options).
TIER_LADDER = ["basic", "premium", "ultra"]

# Status codes that indicate the egress IP / proxy was blocked (or ScraperAPI
# itself failed, e.g. 499 client-closed / 500) and a stronger tier is worth trying.
BLOCK_STATUS = {403, 407, 429, 499, 500, 502, 503, 520, 521, 522, 523, 524}


@dataclass
class FetchResult:
    status_code: int
    headers: httpx.Headers
    text: str
    content: bytes
    url: str
    tier_used: str
    rendered: bool
    elapsed_ms: int
    error: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def ok_transport(self) -> bool:
        """True when we got an HTTP response back (even a 4xx/5xx)."""
        return self.error is None


def _scraperapi_options(
    *,
    country: str,
    device: str,
    tier: str,
    render: bool,
    screenshot: bool,
) -> Dict[str, str]:
    rendering = render or screenshot
    opts: Dict[str, str] = {
        "country_code": country.lower(),
        "device_type": SCRAPERAPI_DEVICE_TYPE.get(device, "desktop"),
    }
    if rendering:
        # Let the headless browser resolve JS/SDK redirects and follow the whole
        # chain. Do NOT send keep_headers here: forwarding our custom UA / client
        # hints to the render engine makes it fail (499). device_type sets the UA.
        opts["render"] = "true"
        opts["follow_redirect"] = "true"
        if screenshot:
            opts["screenshot"] = "true"
    else:
        # Raw HTTP tracing: we follow redirects ourselves so we see every hop,
        # and forward our exact device headers.
        opts["follow_redirect"] = "false"
        opts["keep_headers"] = "true"
    if tier == "premium":
        opts["premium"] = "true"
    elif tier == "ultra":
        opts["ultra_premium"] = "true"
    return opts


def _proxy_url(opts: Dict[str, str]) -> str:
    # username = "scraperapi" + ".key=value" for each option; password = API key.
    username = "scraperapi"
    for key, value in opts.items():
        username += f".{key}={value}"
    api_key = quote(settings.SCRAPERAPI_KEY, safe="")
    return (
        f"http://{username}:{api_key}"
        f"@{settings.SCRAPERAPI_PROXY_HOST}:{settings.SCRAPERAPI_PROXY_PORT}"
    )


class Fetcher:
    """Performs one request per call, via ScraperAPI proxy or directly."""

    def __init__(self, country: str, device: str):
        self.country = country
        self.device = device
        self.enabled = settings.scraperapi_enabled

    async def fetch(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        tier: str = "basic",
        render: bool = False,
        screenshot: bool = False,
        timeout: Optional[float] = None,
    ) -> FetchResult:
        if timeout is None:
            timeout = settings.RENDER_TIMEOUT if (render or screenshot) else settings.REQUEST_TIMEOUT

        if self.enabled:
            return await self._fetch_proxy(
                url, headers=headers, tier=tier, render=render, screenshot=screenshot, timeout=timeout
            )
        return await self._fetch_direct(url, headers=headers, timeout=timeout)

    async def _fetch_direct(
        self, url: str, *, headers: Dict[str, str], timeout: float
    ) -> FetchResult:
        import time

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=timeout, verify=True
            ) as client:
                resp = await client.get(url, headers=headers)
                text = _safe_text(resp)
                return FetchResult(
                    status_code=resp.status_code,
                    headers=resp.headers,
                    text=text,
                    content=resp.content,
                    url=str(resp.url),
                    tier_used="direct",
                    rendered=False,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                )
        except httpx.HTTPError as exc:
            return FetchResult(
                status_code=0,
                headers=httpx.Headers(),
                text="",
                content=b"",
                url=url,
                tier_used="direct",
                rendered=False,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _fetch_proxy(
        self,
        url: str,
        *,
        headers: Dict[str, str],
        tier: str,
        render: bool,
        screenshot: bool,
        timeout: float,
    ) -> FetchResult:
        import time

        opts = _scraperapi_options(
            country=self.country,
            device=self.device,
            tier=tier,
            render=render,
            screenshot=screenshot,
        )
        # During render, ScraperAPI's browser manages headers (keep_headers is off),
        # so send only a minimal Accept-Language and let device_type drive the UA.
        send_headers = headers
        if render or screenshot:
            send_headers = {"Accept-Language": headers.get("Accept-Language", "en-US,en;q=0.9")}
        proxy = _proxy_url(opts)
        start = time.perf_counter()
        # ScraperAPI's proxy performs its own TLS to the target, so we must not
        # verify the proxy's MITM certificate.
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        try:
            async with httpx.AsyncClient(
                proxy=proxy,
                verify=ssl_ctx,
                follow_redirects=False,
                timeout=timeout,
                trust_env=False,
            ) as client:
                resp = await client.get(url, headers=send_headers)
                text = "" if screenshot else _safe_text(resp)
                # ScraperAPI reports the final URL after following redirects here.
                final_url = resp.headers.get("sa-final-url")
                extra = {"final_url": final_url} if final_url else {}
                return FetchResult(
                    status_code=resp.status_code,
                    headers=resp.headers,
                    text=text,
                    content=resp.content,
                    url=str(resp.url),
                    tier_used=tier,
                    rendered=render or screenshot,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    extra=extra,
                )
        except httpx.HTTPError as exc:
            return FetchResult(
                status_code=0,
                headers=httpx.Headers(),
                text="",
                content=b"",
                url=url,
                tier_used=tier,
                rendered=render or screenshot,
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                error=f"{type(exc).__name__}: {exc}",
            )


def _safe_text(resp: httpx.Response) -> str:
    """Decode a response body defensively, capped to the snippet limit x4."""
    try:
        raw = resp.text
    except Exception:  # pragma: no cover - decoding edge cases
        try:
            raw = resp.content.decode("utf-8", errors="replace")
        except Exception:
            return ""
    limit = settings.BODY_SNIPPET_LIMIT * 8
    return raw[:limit]
