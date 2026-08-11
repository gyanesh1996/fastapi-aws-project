from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import httpx
from typing import List, Dict

app = FastAPI(title="URL Redirect Trace Tool")


@app.get("/api/trace")
async def trace_url(url: str = Query(..., description="Target URL to trace")) -> Dict:
    # Ensure scheme is present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    redirect_chain: List[Dict[str, str | int]] = []

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            response = await client.get(url)

            # Record intermediate redirects
            for history_resp in response.history:
                redirect_chain.append({
                    "url": str(history_resp.url),
                    "status_code": history_resp.status_code,
                    "reason": history_resp.reason_phrase or "Redirect"
                })

            # Record final destination
            redirect_chain.append({
                "url": str(response.url),
                "status_code": response.status_code,
                "reason": response.reason_phrase or "OK"
            })

        return {
            "initial_url": url,
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
        <title>URL Redirect Tracer</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f3f4f6; margin: 40px; }
            .container { max-width: 650px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
            h2 { margin-top: 0; color: #111827; }
            .input-group { display: flex; gap: 10px; margin-bottom: 20px; }
            input { flex: 1; padding: 12px; font-size: 15px; border: 1px solid #d1d5db; border-radius: 6px; }
            button { padding: 12px 20px; font-size: 15px; font-weight: 600; background: #2563eb; color: white; border: none; border-radius: 6px; cursor: pointer; }
            button:hover { background: #1d4ed8; }
            .card { background: #f9fafb; border: 1px solid #e5e7eb; border-left: 5px solid #2563eb; padding: 12px 16px; border-radius: 6px; margin-bottom: 10px; }
            .status { font-weight: bold; }
            .status-301, .status-302 { color: #d97706; }
            .status-200 { color: #16a34a; }
            .url { word-break: break-all; font-family: monospace; font-size: 13px; color: #4b5563; }
        </style>
    </head>
    <body>
        <div class="container">
            <h2>URL Redirect Tracer</h2>
            <div class="input-group">
                <input type="text" id="urlInput" placeholder="e.g. google.com or http://bit.ly/..." />
                <button onclick="traceUrl()">Trace</button>
            </div>
            <div id="results"></div>
        </div>

        <script>
            async function traceUrl() {
                const urlInput = document.getElementById('urlInput').value.trim();
                const resultsDiv = document.getElementById('results');
                if (!urlInput) return;

                resultsDiv.innerHTML = "<p>Tracing redirects...</p>";

                try {
                    const res = await fetch(`/api/trace?url=${encodeURIComponent(urlInput)}`);
                    const data = await res.json();

                    if (!res.ok) throw new Error(data.detail || "Trace failed");

                    let html = `<p><strong>Total Redirects:</strong> ${data.total_redirects}</p>`;
                    data.chain.forEach((step, idx) => {
                        html += `
                            <div class="card">
                                <div><strong>Hop ${idx + 1}:</strong> <span class="status status-${step.status_code}">${step.status_code} ${step.reason}</span></div>
                                <div class="url">${step.url}</div>
                            </div>`;
                    });
                    resultsDiv.innerHTML = html;
                } catch (err) {
                    resultsDiv.innerHTML = `<p style="color: red;">Error: ${err.message}</p>`;
                }
            }
        </script>
    </body>
    </html>
    """