import pytest
from httpx import Headers

from app.services import detect, extract, profiles
from app.services.fetcher import FetchResult, Fetcher
from app.services.tracer import trace_url


# --------------------------------------------------------------------------- #
# Platform + destination detection
# --------------------------------------------------------------------------- #
def test_identify_platform():
    assert detect.identify_platform("https://app.adjust.com/abc123")["name"] == "Adjust"
    assert detect.identify_platform("https://demo.onelink.me/xyz")["name"] == "AppsFlyer"
    assert detect.identify_platform("https://demo.app.link/xyz")["name"] == "Branch"
    assert detect.identify_platform("https://play.google.com/store/apps/details?id=com.x")["category"] == "App Store"
    assert detect.identify_platform("https://r.prmin.net/o/out?uh=1") is None


def test_parse_destination_google_play():
    dest = detect.parse_destination("https://play.google.com/store/apps/details?id=com.demo.app&hl=en")
    assert dest["store"] == "Google Play"
    assert dest["package"] == "com.demo.app"


def test_parse_destination_apple():
    dest = detect.parse_destination("https://apps.apple.com/us/app/some-cool-app/id123456789")
    assert dest["store"] == "Apple App Store"
    assert dest["app_id"] == "123456789"
    assert dest["app_name"] == "Some Cool App"


def test_app_scheme_conversion():
    assert detect.to_store_https("market://details?id=com.grad.def&referrer=x") == \
        "https://play.google.com/store/apps/details?id=com.grad.def&referrer=x"
    assert detect.to_store_https("itms-apps://itunes.apple.com/app/id123") == "https://apps.apple.com/app/id123"
    assert detect.is_store_url("market://details?id=com.grad.def")
    # intent:// with an infra ;package= must fall back to the real store URL
    intent = ("intent://x#Intent;scheme=https;package=com.android.vending;"
              "S.browser_fallback_url=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.grad.def;end")
    assert detect.to_store_https(intent) == "https://play.google.com/store/apps/details?id=com.grad.def"


def test_destination_from_query_and_device_aware():
    onelink = ("https://demo.onelink.me/abc?af_android_url=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.foo.bar"
               "&af_ios_url=https%3A%2F%2Fapps.apple.com%2Fapp%2Fid123")
    assert "id=com.foo.bar" in detect.destination_from_query(onelink, "android")
    assert "apps.apple.com" in detect.destination_from_query(onelink, "ios")
    # device-aware body scan when both stores are present
    body = "a https://apps.apple.com/us/app/foo/id999 b https://play.google.com/store/apps/details?id=com.foo.bar c"
    assert "play.google.com" in detect.find_destination(body, "android")
    assert "apps.apple.com" in detect.find_destination(body, "ios")


def test_find_destination_escaped_and_market():
    escaped = 'x={"u":"https:\\/\\/play.google.com\\/store\\/apps\\/details?id=com.grad.def"}'
    assert detect.find_destination(escaped) == "https://play.google.com/store/apps/details?id=com.grad.def"
    encoded = "cta=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.grad.def"
    assert "id=com.grad.def" in (detect.find_destination(encoded) or "")


def test_is_store_url_and_find_store_links():
    assert detect.is_store_url("https://play.google.com/store/apps/details?id=com.x") is True
    assert detect.is_store_url("https://app.adjust.com/abc") is False
    html = 'go here <a href="https://play.google.com/store/apps/details?id=com.demo.app">x</a>'
    assert detect.find_store_links(html) == ["https://play.google.com/store/apps/details?id=com.demo.app"]


# --------------------------------------------------------------------------- #
# Redirect extraction
# --------------------------------------------------------------------------- #
def test_extract_meta_refresh():
    html = '<meta http-equiv="refresh" content="0; url=https://next.example/x">'
    result = extract.find_next_url(base_url="https://a.example", text=html, content_type="text/html", refresh_header=None)
    assert result == ("https://next.example/x", "meta_refresh")


def test_extract_javascript():
    html = "<script>window.location.replace('https://js.example/deep')</script>"
    result = extract.find_next_url(base_url="https://a.example", text=html, content_type="text/html", refresh_header=None)
    assert result == ("https://js.example/deep", "javascript")


def test_extract_json_clickurl():
    body = '{"status":"ok","clickUrl":"https://json.example/final"}'
    result = extract.find_next_url(base_url="https://a.example", text=body, content_type="application/json", refresh_header=None)
    assert result == ("https://json.example/final", "json_clickurl")


def test_extract_relative_resolved():
    html = '<meta http-equiv="refresh" content="0;url=/path/next">'
    result = extract.find_next_url(base_url="https://a.example/start", text=html, content_type="text/html", refresh_header=None)
    assert result == ("https://a.example/path/next", "meta_refresh")


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def test_profiles_normalization():
    assert profiles.normalize_device("ANDROID") == "android"
    assert profiles.normalize_device("weird") == "desktop"
    assert profiles.normalize_country("uk") == "GB"
    assert profiles.normalize_country("zz") == "US"
    headers = profiles.build_headers("android", "IN")
    assert "Android" in headers["User-Agent"]
    assert headers["Accept-Language"].startswith("en-IN")


# --------------------------------------------------------------------------- #
# End-to-end tracer with a mocked fetcher (offline)
# --------------------------------------------------------------------------- #
def _canned(url, status, headers, text=""):
    return FetchResult(
        status_code=status,
        headers=Headers(headers),
        text=text,
        content=text.encode(),
        url=url,
        tier_used="direct",
        rendered=False,
        elapsed_ms=5,
    )


@pytest.mark.anyio
async def test_full_chain_http_then_meta_to_store(monkeypatch):
    start = "https://r.prmin.net/o/out?uh=1"
    hop2 = "https://track.example/hop2"
    store = "https://play.google.com/store/apps/details?id=com.demo.app"

    async def fake_fetch(self, url, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        if url == start:
            return _canned(url, 302, {"location": hop2, "server": "nginx"})
        if url == hop2:
            html = f'<html><meta http-equiv="refresh" content="0; url={store}"></html>'
            return _canned(url, 200, {"content-type": "text/html"}, html)
        if url == store:
            return _canned(url, 200, {"content-type": "text/html"}, "<html>store</html>")
        return _canned(url, 200, {"content-type": "text/html"}, "")

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)

    result = await trace_url(start, device="android", country="IN")

    assert len(result.hops) == 3
    assert result.total_redirects == 2
    assert result.hops[0].status_code == 302
    assert result.hops[0].redirect_type == "http_redirect"
    assert result.hops[1].redirect_type == "meta_refresh"
    assert result.hops[2].redirect_type == "final"
    assert result.final_platform.name == "Google Play"
    assert result.destination.package == "com.demo.app"
    assert result.country == "IN"


@pytest.mark.anyio
async def test_render_resolves_js_interstitial(monkeypatch):
    """A JS 'Redirecting you to the store' page is resolved via sa-final-url."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SCRAPERAPI_KEY", "TESTKEY")
    interstitial = "https://r.prmin.net/o/out?uh=1"
    landing = "https://www.ayetstudios.com/s2/landing/280304/12822/15459/17693?external_identifier=1"

    async def fake_fetch(self, url, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        if "httpbin" in url:
            return _canned(url, 200, {"content-type": "application/json"}, '{"origin":"59.178.102.125"}')
        if render:
            html = '<html><head><meta property="og:title" content="Farm Block Escape"></head><body>x</body></html>'
            res = _canned(landing, 200, {"content-type": "text/html", "sa-final-url": landing}, html)
            res.extra["final_url"] = landing
            return res
        if url == interstitial:
            return _canned(url, 200, {"content-type": "text/html"}, "<html>Redirecting you to the store</html>")
        return _canned(url, 200, {"content-type": "text/html"}, "")

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    result = await trace_url(interstitial, device="android", country="IN")

    assert result.engine == "scraperapi"
    assert any(h.redirect_type == "rendered" for h in result.hops)
    assert result.final_url == landing
    assert result.final_platform.name == "ayeT-Studios"
    assert result.destination.app_name == "Farm Block Escape"
    assert result.egress_ip == "59.178.102.125"


@pytest.mark.anyio
async def test_adjust_market_scheme_redirect(monkeypatch):
    """Adjust 302 -> market://details?id=... (Android) resolves to the Play Store."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SCRAPERAPI_KEY", "K")
    adjust = "https://app.adjust.com/1z7vij5x?campaign=x"
    market = "market://details?id=com.grad.def&referrer=adjust_reftag%3Dabc"

    async def fake_fetch(self, url, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        if "httpbin" in url:
            return _canned(url, 200, {"content-type": "application/json"}, '{"origin":"1.2.3.4"}')
        assert not url.startswith("market://"), "market:// must never be HTTP-fetched"
        if url.startswith("https://play.google.com/store"):
            return _canned(url, 200, {"content-type": "text/html"},
                           '<meta property="og:title" content="Yami Star - Voice Chat - Apps on Google Play">')
        if url.startswith(adjust):
            return _canned(url, 302, {"location": market, "server": "nginx"})
        return _canned(url, 200, {"content-type": "text/html"}, "")

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    result = await trace_url(adjust, device="android", country="IN")

    assert result.final_platform.name == "Google Play"
    assert result.destination.package == "com.grad.def"
    assert result.destination.app_name == "Yami Star - Voice Chat"
    assert result.hops[-1].url.startswith("https://play.google.com/store")


@pytest.mark.anyio
async def test_mmp_fingerprint_resolved_by_bot_ua(monkeypatch):
    """A 200 fingerprint page is resolved by re-fetching with a neutral UA."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SCRAPERAPI_KEY", "K")
    adjust = "https://app.adjust.com/abc?x=1"
    store = "https://play.google.com/store/apps/details?id=com.foo.bar"

    async def fake_fetch(self, url, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        ua = headers.get("User-Agent", "")
        if "httpbin" in url:
            return _canned(url, 200, {"content-type": "application/json"}, '{"origin":"1.2.3.4"}')
        if url.startswith("https://play.google.com/store"):
            return _canned(url, 200, {"content-type": "text/html"}, "<title>Foo Bar - Apps on Google Play</title>")
        if url.startswith(adjust):
            if "Mobile" not in ua:  # neutral/desktop UA -> clean https 302
                return _canned(url, 302, {"location": store})
            return _canned(url, 200, {"content-type": "text/html"}, "<html>fingerprinting, please wait</html>")
        return _canned(url, 200, {"content-type": "text/html"}, "")

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    result = await trace_url(adjust, device="android", country="IN")

    assert result.final_platform.name == "Google Play"
    assert result.destination.package == "com.foo.bar"
    assert any(h.note and "neutral User-Agent" in h.note for h in result.hops)


@pytest.mark.anyio
async def test_loop_is_detected(monkeypatch):
    a = "https://loop.example/a"

    async def fake_fetch(self, url, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        return _canned(url, 302, {"location": a})

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    result = await trace_url(a, device="desktop", country="US")
    assert any("Loop detected" in w for w in result.warnings)


@pytest.mark.anyio
async def test_transport_error_recorded(monkeypatch):
    url = "https://dead.example/x"

    async def fake_fetch(self, u, *, headers, tier="basic", render=False, screenshot=False, timeout=None):
        return FetchResult(0, Headers(), "", b"", u, "direct", False, 1, error="ConnectError: boom")

    monkeypatch.setattr(Fetcher, "fetch", fake_fetch)
    result = await trace_url(url, device="desktop", country="US")
    assert result.hops[-1].redirect_type == "error"
    assert "boom" in (result.hops[-1].note or "")
