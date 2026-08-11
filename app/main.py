import re
import random
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI(title="Advanced URL Redirect Tracer")

USER_AGENTS = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "android": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
}

COUNTRY_LANGUAGES = {
    "US": "en-US,en;q=0.9",
    "IN": "en-IN,en;q=0.9",
    "GB": "en-GB,en;q=0.9",
    "DE": "de-DE,de;q=0.9",
    "FR": "fr-FR,fr;q=0.9",
}

US_IPS = ["24.227.39.184", "3.221.144.220", "16.179.114.232"]
IN_IPS = ["121.241.186.43", "47.8.81.126", "98.70.191.81"]

def get_spoofed_ip(country: str) -> str:
    return random.choice(IN_IPS) if country.upper() == "IN" else random.choice(US_IPS)

def extract_js_or_meta_redirect(html_content: str) -> str | None:
    """Finds client-side redirects embedded in HTML or JS execution code."""
    # Check Meta refresh tag
    meta_match = re.search(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\']\d+;\s*url=([^"\']+)["\']', html_content, re.I)
    if meta_match:
        return meta_match.group(1)

    # Check JS window.location / href assignments
    js_match = re.search(r'(?:window\.location(?:\.href)?|location\.href)\s*=\s*["\']([^"\']+)["\']', html_content, re.I)
    if js_match:
        return js_match.group(1)

    return None

@app.get("/api/trace")
async def trace_url(
    url: str = Query(..., description="Target URL"),
    device: str = Query("android", description="Device type"),
    country: str = Query("IN", description="Country code")
) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    ua = USER_AGENTS.get(device.lower(), USER_AGENTS["android"])
    lang = COUNTRY_LANGUAGES.get(country.upper(), COUNTRY_LANGUAGES["IN"])
    ip = get_spoofed_ip(country)

    base_headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "X-Forwarded-For": ip,
        "X-Real-IP": ip,
        "CF-Connecting-IP": ip,
    }

    redirect_chain: List[Dict[str, Any]] = []
    visited = set()
    current_url = url
    max_steps = 10

    async with httpx.AsyncClient(follow_redirects=False, timeout=15.0, verify=False) as client:
        for _ in range(max_steps):
            if not current_url or current_url in visited:
                break
            visited.add(current_url)

            # Pass Referer header from previous hop if available
            headers = base_headers.copy()
            if redirect_chain:
                headers["Referer"] = redirect_chain[-1]["url"]
                headers["Sec-Fetch-Site"] = "cross-site"

            try:
                resp = await client.get(current_url, headers=headers)
            except Exception as exc:
                redirect_chain.append({
                    "url": current_url,
                    "status_code": 500,
                    "reason": f"Request Failed: {str(exc)}",
                    "response_body": None
                })
                break

            body_data = None
            next_target = None

            # 1. Handle HTTP standard redirects (301, 302, 303, 307, 308)
            if resp.is_redirect or "location" in resp.headers:
                next_target = resp.headers.get("location")
            else:
                # 2. Check JSON bodies for embedded click URLs
                try:
                    json_data = resp.json()
                    body_data = json_data
                    if isinstance(json_data, dict):
                        next_target = (
                            json_data.get("clickUrl") or 
                            json_data.get("click_url") or 
                            json_data.get("url") or 
                            json_data.get("redirect")
                        )
                except Exception:
                    # 3. Check HTML body for Meta refresh or JS location redirects
                    if len(resp.text) < 10000:
                        body_data = resp.text
                        next_target = extract_js_or_meta_redirect(resp.text)

            redirect_chain.append({
                "url": str(resp.url),
                "status_code": resp.status_code,
                "reason": resp.reason_phrase or "OK",
                "response_body": body_data
            })

            if next_target:
                # Resolve relative URLs
                current_url = str(httpx.URL(current_url).join(next_target))
            else:
                break

    return {
        "initial_url": url,
        "device": device,
        "country": country,
        "spoofed_ip": ip,
        "total_redirects": len(redirect_chain) - 1 if len(redirect_chain) > 1 else 0,
        "chain": redirect_chain
    }

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Tracking Link Tracer</title>
        <style>
            body { font-family: sans-serif; padding: 30px; background: #f4f6f8; }
            .box { max-width: 800px; margin: 0 auto; background: white; padding: 25px; border-radius: 8px; }
            input, select, button { padding: 10px; margin: 5px 0; width: 100%; box-sizing: border-box; }
            button { background: #8b5cf6; color: white; border: none; font-weight: bold; cursor: pointer; }
            .card { background: #fafafa; border-left: 4px solid #8b5cf6; padding: 12px; margin-top: 10px; word-break: break-all; }
        </style>
    </head>
    <body>
        <div class="box">
            <h2>Tracking Link Tracer</h2>
            <input type="text" id="url" placeholder="Enter tracking link...">
            <select id="device">
                <option value="android">Android</option>
                <option value="ios">iOS</option>
                <option value="desktop">Desktop</option>
            </select>
            <select id="country">
                <option value="IN">India</option>
                <option value="US">United States</option>
            </select>
            <button onclick="runTrace()">SUBMIT</button>
            <div id="out"></div>
        </div>
        <script>
            async function runTrace() {
                const u = document.getElementById('url').value;
                const d = document.getElementById('device').value;
                const c = document.getElementById('country').value;
                const out = document.getElementById('out');
                out.innerHTML = "Tracing...";
                
                const res = await fetch(`/api/trace?url=${encodeURIComponent(u)}&device=${d}&country=${c}`);
                const data = await res.json();
                
                let h = `<h4>Total Redirections: ${data.total_redirects}</h4>`;
                data.chain.forEach((s, i) => {
                    h += `<div class="card"><strong>Step ${i+1} (${s.status_code}):</strong> ${s.url}</div>`;
                });
                out.innerHTML = h;
            }
        </script>
    </body>
    </html>
    """