from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx
from typing import List, Dict

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


@app.get("/api/trace")
async def trace_url(
    url: str = Query(..., description="Target URL"),
    device: str = Query("desktop", description="Device type: desktop, android, ios"),
    country: str = Query("US", description="Country code: US, GB, IN, DE, FR")
) -> Dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    user_agent = USER_AGENTS.get(device.lower(), USER_AGENTS["desktop"])
    accept_language = COUNTRY_LANGUAGES.get(country.upper(), COUNTRY_LANGUAGES["US"])

    headers = {
        "User-Agent": user_agent,
        "Accept-Language": accept_language,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    redirect_chain: List[Dict[str, str | int]] = []

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=12.0, headers=headers) as client:
            response = await client.get(url)

            for history_resp in response.history:
                redirect_chain.append({
                    "url": str(history_resp.url),
                    "status_code": history_resp.status_code,
                    "reason": history_resp.reason_phrase or "Redirect"
                })

            redirect_chain.append({
                "url": str(response.url),
                "status_code": response.status_code,
                "reason": response.reason_phrase or "OK"
            })

        return {
            "initial_url": url,
            "device": device,
            "country": country,
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

            .url-box:focus {
                border-color: #a855f7;
                box-shadow: 0 0 0 4px rgba(168, 85, 247, 0.15);
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
                cursor: pointer;
            }

            select:focus {
                border-color: #a855f7;
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
                letter-spacing: 0.5px;
                box-shadow: 0 4px 14px rgba(168, 85, 247, 0.4);
                transition: transform 0.1s, box-shadow 0.2s;
            }

            .submit-btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 20px rgba(168, 85, 247, 0.6);
            }

            .card {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-left: 6px solid #a855f7;
                padding: 16px;
                border-radius: 10px;
                margin-top: 14px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.04);
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
                    <option value="GB">United Kingdom</option>
                    <option value="IN">India</option>
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

                    let html = `<h3 style="color:#1e293b;">Total Redirections: ${data.total_redirects}</h3>`;
                    data.chain.forEach((step, idx) => {
                        html += `
                            <div class="card">
                                <div><strong>Step ${idx + 1}:</strong> <span class="status status-${step.status_code}">${step.status_code} ${step.reason}</span></div>
                                <div class="url-text">${step.url}</div>
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