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
