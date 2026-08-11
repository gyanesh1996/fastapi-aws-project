from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx
import random
from typing import List, Dict, Any

app = FastAPI(title="Advanced URL Redirect Tracer")

USER_AGENTS = {
    "desktop": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "android": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
}

COUNTRY_LANGUAGES = {
    "US": "en-US,en;q=0.9",
    "GB": "en-GB,en;q=0.9",
    "IN": "en-IN,en;q=0.9",
    "DE": "de-DE,de;q=0.9",
    "FR": "fr-FR,fr;q=0.9",
}

US_IPS = [
    "16.179.114.232", "9.94.110.41", "22.184.83.20", "24.164.96.187", "9.176.58.32",
    "40.111.207.210", "12.156.95.66", "22.72.67.81", "23.238.58.32", "9.132.222.60",
    "11.94.33.236", "13.27.98.249", "30.101.17.180", "12.181.245.121", "16.0.87.149",
    "38.68.111.158", "32.204.187.226", "8.83.50.244", "23.63.76.223", "30.177.209.211",
    "24.227.39.184", "3.221.144.220", "7.193.241.125", "28.12.231.21", "20.1.196.6"
]

IN_IPS = [
    "47.8.81.126", "98.70.191.81", "103.175.95.214", "121.241.186.43", "49.41.77.36",
    "47.29.100.43", "122.168.20.81", "59.91.43.91", "20.235.135.151", "122.170.16.15"
]


def get_spoofed_ip(country: str) -> str:
    country_upper = country.upper()
    if country_upper == "IN":
        return random.choice(IN_IPS)
    return random.choice(US_IPS)


@app.get("/api/trace")
async def trace_url(
    url: str = Query(..., description="Target URL"),
    device: str = Query("desktop", description="Device type: desktop, android, ios"),
    country: str = Query("US", description="Country code: US, GB, IN, DE, FR")
) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    user_agent = USER_AGENTS.get(device.lower(), USER_AGENTS["desktop"])
    accept_language = COUNTRY_LANGUAGES.get(country.upper(), COUNTRY_LANGUAGES["US"])
    spoofed_ip = get_spoofed_ip(country)

    headers = {
        "User-Agent": user_agent,
        "Accept-Language": accept_language,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "X-Forwarded-For": spoofed_ip,
        "X-Real-IP": spoofed_ip,
        "CF-Connecting-IP": spoofed_ip,
        "X-Client-IP": spoofed_ip
    }

    redirect_chain: List[Dict[str, Any]] = []
    visited_urls = set()
    current_url = url

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0, headers=headers) as client:
            max_depth = 10
            depth = 0

            while current_url and current_url not in visited_urls and depth < max_depth:
                visited_urls.add(current_url)
                depth += 1

                response = await client.get(current_url)

                for history_resp in response.history:
                    redirect_chain.append({
                        "url": str(history_resp.url),
                        "status_code": history_resp.status_code,
                        "reason": history_resp.reason_phrase or "Redirect",
                        "response_body": None
                    })

                body_content = None
                next_url_from_json = None

                try:
                    body_json = response.json()
                    body_content = body_json
                    if isinstance(body_json, dict):
                        # Extract next destination from common tracking JSON fields
                        next_url_from_json = (
                            body_json.get("clickUrl") or 
                            body_json.get("click_url") or 
                            body_json.get("url") or 
                            body_json.get("redirect")
                        )
                except Exception:
                    if "application/json" in response.headers.get("content-type", "") or len(response.text) < 1000:
                        body_content = response.text

                redirect_chain.append({
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "reason": response.reason_phrase or "OK",
                    "response_body": body_content
                })

                # If JSON payload contains a clickUrl, follow it to reveal the final landing page
                if next_url_from_json and isinstance(next_url_from_json, str):
                    current_url = next_url_from_json
                else:
                    break

        return {
            "initial_url": url,
            "device": device,
            "country": country,
            "spoofed_ip": spoofed_ip,
            "total_redirects": len(redirect_chain) - 1,
            "chain": redirect_chain
        }

    except httpx.RequestError as exc:
        raise HTTPException(status_code=400, detail=f"Failed to trace URL: {str(exc)}")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Affiliate Link & Redirect Tracer</title>
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 40px 20px;
                min-height: 100vh;
                background: url('https://img.freepik.com/free-vector/blurred-bokeh-light-red-background_260559-335.jpg?w=1480') no-repeat center center fixed;
                background-size: cover;
                display: flex;
                justify-content: center;
                align-items: flex-start;
            }

            .container {
                width: 100%;
                max-width: 900px;
                background: rgba(255, 255, 255, 0.94);
                backdrop-filter: blur(8px);
                padding: 35px;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                border: 1px solid rgba(255, 255, 255, 0.4);
            }

            .tabs {
                display: flex;
                gap: 20px;
                border-bottom: 2px solid #e2e8f0;
                margin-bottom: 25px;
            }

            .tab-btn {
                padding: 10px 15px;
                font-weight: 700;
                cursor: pointer;
                border: none;
                background: none;
                color: #a855f7;
                font-size: 17px;
                border-bottom: 3px solid #a855f7;
            }

            .url-box {
                width: 100%;
                padding: 16px;
                font-size: 16px;
                border: 2px solid #cbd5e1;
                border-radius: 10px;
                margin-bottom: 20px;
                outline: none;
                transition: border-color 0.2s, box-shadow 0.2s;
            }

            .controls-grid {
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }

            select {
                flex: 1;
                min-width: 180px;
                padding: 14px;
                border: 2px solid #cbd5e1;
                border-radius: 10px;
                font-size: 15px;
                background: white;
                outline: none;
            }

            .submit-btn {
                padding: 14px 40px;
                font-weight: 700;
                background: linear-gradient(135deg, #a855f7 0%, #7e22ce 100%);
                color: white;
                border: none;
                border-radius: 10px;
                cursor: pointer;
                font-size: 16px;
                box-shadow: 0 4px 14px rgba(168, 85, 247, 0.4);
            }

            .card {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-left: 6px solid #a855f7;
                padding: 16px;
                border-radius: 10px;
                margin-top: 14px;
            }

            .status-301, .status-302 { color: #d97706; font-weight: bold; }
            .status-200 { color: #16a34a; font-weight: bold; }

            .url-text {
                font-family: "Fira Code", Monaco, Consolas, monospace;
                word-break: break-all;
                color: #334155;
                margin-top: 6px;
                font-size: 14px;
            }

            .info-badge {
                display: inline-block;
                background: #f1f5f9;
                color: #475569;
                padding: 4px 10px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
                margin-bottom: 12px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="tabs">
                <button class="tab-btn">Tracking Link</button>
            </div>

            <input type="text" id="urlInput" class="url-box" placeholder="Enter your affiliate/tracking link..." />

            <div class="controls-grid">
                <select id="deviceSelect">
                    <option value="android">Android</option>
                    <option value="ios">iOS (iPhone)</option>
                    <option value="desktop">Desktop (Windows/Chrome)</option>
                </select>

                <select id="countrySelect">
                    <option value="US">United States</option>
                    <option value="IN">India</option>
                    <option value="GB">United Kingdom</option>
                    <option value="DE">Germany</option>
                    <option value="FR">France</option>
                </select>

                <button class="submit-btn" onclick="traceUrl()">SUBMIT</button>
            </div>

            <div id="results" style="margin-top: 30px;"></div>
        </div>

        <script>
            async function traceUrl() {
                const url = document.getElementById('urlInput').value.trim();
                const device = document.getElementById('deviceSelect').value;
                const country = document.getElementById('countrySelect').value;
                const resultsDiv = document.getElementById('results');

                if (!url) return;
                resultsDiv.innerHTML = "<p style='color:#64748b; font-weight:600;'>Tracing link redirections...</p>";

                try {
                    const endpoint = `/api/trace?url=${encodeURIComponent(url)}&device=${device}&country=${country}`;
                    const res = await fetch(endpoint);
                    const data = await res.json();

                    if (!res.ok) throw new Error(data.detail || "Trace failed");

                    let html = `<div class="info-badge">Spoofed IP: <strong>${data.spoofed_ip}</strong> (${data.country})</div>`;
                    html += `<h3 style="color:#1e293b; margin-top: 5px;">Total Redirections: ${data.total_redirects}</h3>`;
                    
                    data.chain.forEach((step, idx) => {
                        let bodyHtml = '';
                        if (step.response_body) {
                            const bodyStr = typeof step.response_body === 'object' 
                                ? JSON.stringify(step.response_body, null, 2) 
                                : step.response_body;
                            bodyHtml = `<pre style="background: #1e293b; color: #f8fafc; padding: 12px; border-radius: 6px; font-size: 13px; overflow-x: auto; margin-top: 10px; white-space: pre-wrap; word-break: break-all;">${bodyStr}</pre>`;
                        }

                        html += `
                            <div class="card">
                                <div><strong>Step ${idx + 1}:</strong> <span class="status status-${step.status_code}">${step.status_code} ${step.reason}</span></div>
                                <div class="url-text">${step.url}</div>
                                ${bodyHtml}
                            </div>`;
                    });
                    resultsDiv.innerHTML = html;
                } catch (err) {
                    resultsDiv.innerHTML = `<p style="color: #ef4444; font-weight:600;">Error: ${err.message}</p>`;
                }
            }
        </script>
    </body>
    </html>
    """