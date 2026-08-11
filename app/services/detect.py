"""Identify tracking platforms and final app-store destinations from a URL.

This powers the platform badges (Adjust, AppsFlyer, Branch, ...) shown in the
chain, mirroring what AffiliTest displays for each hop, plus extraction of the
final app-store destination (package / app id / name).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

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


def identify_platform(url: str) -> Optional[Dict[str, str]]:
    """Return {name, category, icon} for a recognised platform, else None."""
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
    platform = identify_platform(url)
    return bool(platform and platform["category"] == STORE_CATEGORY)


# App-store links found inside a rendered page (used when JS resolves to a store).
_STORE_LINK_RE = re.compile(
    r"https?://(?:play\.google\.com/store/apps/details\?[^\s\"'<>]+"
    r"|apps\.apple\.com/[^\s\"'<>]+"
    r"|itunes\.apple\.com/[^\s\"'<>]+)",
    re.IGNORECASE,
)


def find_store_links(html: str) -> List[str]:
    """All app-store URLs embedded in an HTML/JS blob, de-duplicated in order."""
    seen: List[str] = []
    for match in _STORE_LINK_RE.findall(html or ""):
        cleaned = match.rstrip("\\\"'),;")
        if cleaned not in seen:
            seen.append(cleaned)
    return seen
