"""Identify tracking platforms and final app-store destinations from a URL.

This powers the platform badges (Adjust, AppsFlyer, Branch, ...) shown in the
chain, mirroring what AffiliTest displays for each hop, plus extraction of the
final app-store destination (package / app id / name).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

# (display name, category, icon emoji, [host substrings]). First match wins, so
# keep more specific entries above generic ones.
PLATFORM_SIGNATURES: List[Tuple[str, str, str, List[str]]] = [
    # --- Mobile Measurement Partners / attribution ---
    ("Adjust", "Attribution (MMP)", "📊", ["adjust.com", "adj.st", "go.link", "adjust.io"]),
    ("AppsFlyer", "Attribution (MMP)", "📊", ["onelink.me", "appsflyer.com", "onelnk.com", "af-onelink"]),
    ("Branch", "Attribution (MMP)", "🌿", ["app.link", "bnc.lt", "branch.io", "test-app.link"]),
    ("Singular", "Attribution (MMP)", "📈", ["sng.link", "singular.net"]),
    ("Kochava", "Attribution (MMP)", "🅺", ["kochava.com", "smart.link", "kochavatracking.com"]),
    ("Tenjin", "Attribution (MMP)", "🇹", ["tenjin.io", "tenjin.com"]),
    ("Airbridge", "Attribution (MMP)", "✈️", ["airbridge.io", "abr.ge"]),
    ("AppMetrica", "Attribution (MMP)", "📊", ["appmetrica.yandex", "redirect.appmetrica"]),
    # --- Offerwalls / rewarded-play landing pages (common final destinations) ---
    ("ayeT-Studios", "Offerwall", "🎮", ["ayetstudios.com", "ayet.io"]),
    ("AdGate Media", "Offerwall", "🎮", ["adgatemedia.com", "adscendmedia.com"]),
    ("BitLabs", "Offerwall", "🎮", ["bitlabs.ai", "web.bitlabs"]),
    ("Tapjoy", "Offerwall", "🎮", ["tapjoy.com", "tjoy.me"]),
    ("Fyber / Digital Turbine", "Offerwall", "🎮", ["fyber.com", "offer.fyber", "digitalturbine"]),
    # --- Tracking / redirect platforms ---
    ("TUNE / HasOffers", "Tracker", "🔗", ["hasoffers.com", "go2cloud.org", "tune.com", ".7eer.", ".evyy."]),
    ("Everflow", "Tracker", "🔗", ["everflow", ".efwa.", "eflow"]),
    ("Voluum", "Tracker", "🔗", ["voluum.com", ".vlmtrk.", "voluumtrk"]),
    ("Affise", "Tracker", "🔗", ["affise", "go.aff"]),
    ("Cake", "Tracker", "🔗", ["cakemarketing", "cranktank"]),
    ("Impact", "Tracker", "🔗", ["impact.com", ".sjv.io", ".pxf.io", "ojrq.net"]),
    ("PartnerStack", "Tracker", "🔗", ["partnerstack", "pxf.io"]),
    # --- Ad networks / DSPs / exchanges ---
    ("Google Ads", "Ad Network", "🅶", ["googleadservices.com", "doubleclick.net", "googlesyndication.com"]),
    ("The Trade Desk", "Ad Network", "📺", ["adsrvr.org"]),
    ("Meta Ads", "Ad Network", "📘", ["facebook.com/tr", "fb.me", "atdmt.com"]),
    ("Taboola", "Ad Network", "📰", ["taboola.com", "trc.taboola"]),
    ("Outbrain", "Ad Network", "📰", ["outbrain.com", "zemanta"]),
    ("Unity Ads", "Ad Network", "🎮", ["unityads.unity3d.com", "unity3d.com"]),
    ("ironSource", "Ad Network", "⛓️", ["ironsrc", "ironsource"]),
    ("Moloco", "Ad Network", "🧬", ["moloco.com", "molocoads"]),
    ("Liftoff", "Ad Network", "🚀", ["liftoff.io", "vungle.com"]),
    ("AppLovin", "Ad Network", "💠", ["applovin.com", "applvn.com"]),
    ("Mintegral", "Ad Network", "🧩", ["mintegral.com", "mtgglobals.com"]),
    # --- App stores (terminal destinations) ---
    ("Google Play", "App Store", "🤖", ["play.google.com", "play.app.goo.gl", "market.android.com"]),
    ("Apple App Store", "App Store", "", ["apps.apple.com", "itunes.apple.com", "apple.co"]),
    ("Galaxy Store", "App Store", "📱", ["galaxystore.samsung.com", "samsungapps.com"]),
    ("Huawei AppGallery", "App Store", "📱", ["appgallery.huawei.com", "appgallery.cloud.huawei"]),
    ("Amazon Appstore", "App Store", "📦", ["amazon.com/gp/mas", "amazon.com/dp"]),
    ("Microsoft Store", "App Store", "🪟", ["apps.microsoft.com", "microsoft.com/store"]),
    # --- CDNs / shorteners sometimes seen mid-chain ---
    ("Bitly", "Shortener", "🔗", ["bit.ly", "bitly.com"]),
    ("TinyURL", "Shortener", "🔗", ["tinyurl.com"]),
]

STORE_CATEGORY = "App Store"


# App-scheme deep links used by Android/iOS: market://, intent://, itms-apps://,
# android-app://. These appear as redirect Location headers when the client looks
# like a real device, and their target package/app id must be parsed out.
_MARKET_ID_RE = re.compile(r"[?&]id=([a-zA-Z0-9._]+)")
_INTENT_PKG_RE = re.compile(r"[;#]package=([a-zA-Z0-9._]+)")
_INTENT_FALLBACK_RE = re.compile(r"S\.browser_fallback_url=([^;\s\"'<>]+)")
_ITMS_ID_RE = re.compile(r"id(\d+)")

# Store/browser apps that appear as intent ;package= but are NOT the target app.
INFRA_PACKAGES = {
    "com.android.vending",
    "com.android.chrome",
    "com.google.android.gms",
    "com.sec.android.app.samsungapps",
    "com.huawei.appmarket",
}


def scheme_of(url: str) -> str:
    return (url.split(":", 1)[0] or "").lower() if ":" in url else ""


def is_app_scheme(url: str) -> bool:
    return scheme_of(url) in ("market", "intent", "itms-apps", "itms-appss", "android-app")


def to_store_https(url: str) -> Optional[str]:
    """Convert an app-scheme deep link to its https store URL (best effort)."""
    scheme = scheme_of(url)
    if scheme == "market":
        match = _MARKET_ID_RE.search(url)
        if match:
            query = url.split("?", 1)[1] if "?" in url else f"id={match.group(1)}"
            return f"https://play.google.com/store/apps/details?{query}"
    if scheme == "android-app":
        pkg = url[len("android-app://"):].split("/")[0].split("?")[0]
        if pkg:
            return f"https://play.google.com/store/apps/details?id={pkg}"
    if scheme == "intent":
        # intent://...#Intent;...;package=<pkg>;S.browser_fallback_url=<url>;end
        # The ;package= is often the store app (com.android.vending), not the
        # target — prefer an explicit id=, then a store fallback URL.
        id_match = _MARKET_ID_RE.search(url)
        if id_match and id_match.group(1) not in INFRA_PACKAGES:
            return f"https://play.google.com/store/apps/details?id={id_match.group(1)}"
        fallback = _INTENT_FALLBACK_RE.search(url)
        if fallback:
            fb = unquote(fallback.group(1))
            if "play.google.com" in fb or "apps.apple.com" in fb:
                return fb
        pkg_match = _INTENT_PKG_RE.search(url)
        if pkg_match and pkg_match.group(1) not in INFRA_PACKAGES:
            return f"https://play.google.com/store/apps/details?id={pkg_match.group(1)}"
    if scheme in ("itms-apps", "itms-appss"):
        match = _ITMS_ID_RE.search(url)
        if match:
            return f"https://apps.apple.com/app/id{match.group(1)}"
    return None


def identify_platform(url: str) -> Optional[Dict[str, str]]:
    """Return {name, category, icon} for a recognised platform, else None."""
    if is_app_scheme(url):
        https = to_store_https(url)
        if https:
            return identify_platform(https)
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    haystack = host
    # A few signatures key off a path (e.g. facebook.com/tr); include it.
    full = url.lower()
    for name, category, icon, needles in PLATFORM_SIGNATURES:
        for needle in needles:
            target = full if "/" in needle else haystack
            if needle in target:
                return {"name": name, "category": category, "icon": icon}
    return None


_APPLE_ID_RE = re.compile(r"/id(\d+)")
_APPLE_NAME_RE = re.compile(r"/app/([^/]+)/id\d+")


def parse_destination(url: str) -> Optional[Dict[str, str]]:
    """Extract app-store destination details from a terminal store URL."""
    if is_app_scheme(url):
        https = to_store_https(url)
        if https:
            url = https
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)

    if "play.google.com" in host or "market.android.com" in host:
        package = (query.get("id") or [""])[0]
        return {
            "store": "Google Play",
            "package": package,
            "app_name": package,
            "url": url,
        }

    if "apps.apple.com" in host or "itunes.apple.com" in host:
        app_id_match = _APPLE_ID_RE.search(parsed.path)
        name_match = _APPLE_NAME_RE.search(parsed.path)
        app_id = app_id_match.group(1) if app_id_match else ""
        slug = name_match.group(1).replace("-", " ").title() if name_match else ""
        return {
            "store": "Apple App Store",
            "app_id": app_id,
            "app_name": slug,
            "url": url,
        }

    return None


def is_store_url(url: str) -> bool:
    if is_app_scheme(url):
        return to_store_https(url) is not None
    platform = identify_platform(url)
    return bool(platform and platform["category"] == STORE_CATEGORY)


# App-store links + app-scheme deep links embedded in an HTML/JS blob. Ordered by
# how directly they name the destination.
_STORE_LINK_RE = re.compile(
    r"https?://(?:play\.google\.com/store/apps/details\?[^\s\"'<>\\]+"
    r"|(?:apps|itunes)\.apple\.com/[^\s\"'<>\\]+)",
    re.IGNORECASE,
)
_MARKET_LINK_RE = re.compile(r"market://details\?[^\s\"'<>\\]+", re.IGNORECASE)
_INTENT_LINK_RE = re.compile(r"intent://[^\s\"'<>]*?package=[a-zA-Z0-9._]+", re.IGNORECASE)
_ITMS_LINK_RE = re.compile(r"itms-appss?://[^\s\"'<>\\]*id\d+", re.IGNORECASE)


def _unescape(html: str) -> str:
    """Undo the common escaping that hides URLs inside JS/JSON strings, including
    URL-encoded forms (%2F/%3A) which some networks double-encode."""
    text = (
        (html or "")
        .replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("&#47;", "/")
        .replace("&amp;", "&")
    )
    for _ in range(2):
        low = text.lower()
        if "%2f" in low or "%3a" in low or "%3d" in low:
            try:
                text = unquote(text)
            except Exception:
                break
        else:
            break
    return text


def find_store_links(html: str) -> List[str]:
    """All app-store URLs embedded in an HTML/JS blob, de-duplicated in order."""
    text = _unescape(html)
    seen: List[str] = []
    for match in _STORE_LINK_RE.findall(text):
        cleaned = match.rstrip("\\\"'),;")
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _is_apple(url: str) -> bool:
    low = url.lower()
    return "apps.apple.com" in low or "itunes.apple.com" in low


def _is_google(url: str) -> bool:
    low = url.lower()
    return "play.google.com" in low or "market.android.com" in low


def find_destination(html: str, device: str = "android") -> Optional[str]:
    """Best https store URL derivable from a raw interstitial/fingerprint page.

    Looks for direct store links first (choosing the one matching the device when
    both platforms are present), then Android/iOS app-scheme deep links
    (market://, intent://, itms-apps://) which are converted to https.
    """
    text = _unescape(html)
    want_apple = device == "ios"

    store_links = find_store_links(html)
    if store_links:
        apple = [u for u in store_links if _is_apple(u)]
        google = [u for u in store_links if _is_google(u)]
        if want_apple and apple:
            return apple[0]
        if not want_apple and google:
            return google[0]
        return store_links[0]

    scheme_order = (
        (_ITMS_LINK_RE, _MARKET_LINK_RE, _INTENT_LINK_RE)
        if want_apple
        else (_MARKET_LINK_RE, _INTENT_LINK_RE, _ITMS_LINK_RE)
    )
    for pattern in scheme_order:
        match = pattern.search(text)
        if match:
            https = to_store_https(match.group(0).rstrip("\\\"'),;"))
            if https:
                return https
    return None


# Query params that carry the real store/deeplink URL on MMP links.
# AppsFlyer OneLink: af_android_url / af_ios_url / af_dp / af_web_dp / af_r.
# Adjust overrides: redirect / redirect_android / redirect_ios.
_QUERY_DEST_KEYS_ANDROID = ["af_android_url", "af_dp", "af_web_dp", "redirect_android", "url", "redirect", "af_r"]
_QUERY_DEST_KEYS_IOS = ["af_ios_url", "af_dp", "af_web_dp", "redirect_ios", "url", "redirect", "af_r"]


def destination_from_query(url: str, device: str = "android") -> Optional[str]:
    """Extract a store/deeplink destination embedded in an MMP link's own query
    string (AppsFlyer OneLink af_* params, Adjust redirect_* overrides)."""
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    keys = _QUERY_DEST_KEYS_IOS if device == "ios" else _QUERY_DEST_KEYS_ANDROID
    for key in keys:
        for raw in query.get(key, []):
            candidate = unquote(raw)
            if is_app_scheme(candidate):
                https = to_store_https(candidate)
                if https:
                    return https
            elif is_store_url(candidate):
                return candidate
    return None
