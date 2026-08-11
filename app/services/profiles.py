"""Device and geography request profiles.

These build the User-Agent / client-hint / Accept-Language headers that make a
request look like a real phone or desktop browser from a given country. The
egress IP itself is handled by the proxy layer (see fetcher.py) — headers alone
never fool a serious anti-bot system, but they must still be consistent with the
device and locale we claim to be.
"""

from __future__ import annotations

from typing import Dict

# Realistic, current-ish user agents per device class.
USER_AGENTS: Dict[str, str] = {
    "desktop": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "android": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
    ),
    "ios": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
    ),
}

# device_type value passed to ScraperAPI (it only distinguishes mobile/desktop).
SCRAPERAPI_DEVICE_TYPE: Dict[str, str] = {
    "desktop": "desktop",
    "android": "mobile",
    "ios": "mobile",
}

# Country code -> (Accept-Language, human label). Keys are ISO country codes as
# selected in the UI; values feed both the header and the proxy country_code.
COUNTRY_PROFILES: Dict[str, Dict[str, str]] = {
    "US": {"accept_language": "en-US,en;q=0.9", "label": "United States"},
    "IN": {"accept_language": "en-IN,en;q=0.9,hi;q=0.8", "label": "India"},
    "GB": {"accept_language": "en-GB,en;q=0.9", "label": "United Kingdom"},
    "DE": {"accept_language": "de-DE,de;q=0.9,en;q=0.8", "label": "Germany"},
    "FR": {"accept_language": "fr-FR,fr;q=0.9,en;q=0.8", "label": "France"},
    "CA": {"accept_language": "en-CA,en;q=0.9,fr;q=0.8", "label": "Canada"},
    "AU": {"accept_language": "en-AU,en;q=0.9", "label": "Australia"},
    "BR": {"accept_language": "pt-BR,pt;q=0.9,en;q=0.8", "label": "Brazil"},
    "ID": {"accept_language": "id-ID,id;q=0.9,en;q=0.8", "label": "Indonesia"},
    "AE": {"accept_language": "ar-AE,ar;q=0.9,en;q=0.8", "label": "United Arab Emirates"},
    "SG": {"accept_language": "en-SG,en;q=0.9", "label": "Singapore"},
    "JP": {"accept_language": "ja-JP,ja;q=0.9,en;q=0.8", "label": "Japan"},
}


def normalize_device(device: str) -> str:
    d = (device or "").lower().strip()
    return d if d in USER_AGENTS else "desktop"


def normalize_country(country: str) -> str:
    c = (country or "").upper().strip()
    # Common alias: some UIs send "UK" for the United Kingdom.
    if c == "UK":
        c = "GB"
    return c if c in COUNTRY_PROFILES else "US"


def build_headers(device: str, country: str) -> Dict[str, str]:
    """Browser-consistent headers for the given device + country."""
    device = normalize_device(device)
    country = normalize_country(country)
    ua = USER_AGENTS[device]
    accept_language = COUNTRY_PROFILES[country]["accept_language"]

    headers = {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.8,image/avif,image/webp,*/*;q=0.7"
        ),
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    }

    is_mobile = device in ("android", "ios")
    if device == "android":
        headers["sec-ch-ua"] = '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"'
        headers["sec-ch-ua-mobile"] = "?1"
        headers["sec-ch-ua-platform"] = '"Android"'
    elif device == "desktop":
        headers["sec-ch-ua"] = '"Chromium";v="126", "Google Chrome";v="126", "Not.A/Brand";v="24"'
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'
    # iOS Safari does not send sec-ch-ua hints; omit them there.

    headers["Sec-Fetch-Dest"] = "document"
    headers["Sec-Fetch-Mode"] = "navigate"
    headers["Sec-Fetch-Site"] = "none"
    headers["Sec-Fetch-User"] = "?1"
    if is_mobile:
        headers["Viewport-Width"] = "412" if device == "android" else "390"
    return headers
