from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Platform(BaseModel):
    name: str
    category: str
    icon: str = ""


class Hop(BaseModel):
    step: int
    url: str
    method: str = "GET"
    status_code: Optional[int] = None
    reason: str = ""
    # How we moved from this hop to the next one:
    # http_redirect | meta_refresh | javascript | json_clickurl | rendered | final | error
    redirect_type: str = "final"
    location: Optional[str] = None
    platform: Optional[Platform] = None
    server: Optional[str] = None
    content_type: Optional[str] = None
    tier_used: str = "direct"
    rendered: bool = False
    elapsed_ms: int = 0
    note: Optional[str] = None
    body_snippet: Optional[str] = None


class Destination(BaseModel):
    store: Optional[str] = None
    app_name: Optional[str] = None
    package: Optional[str] = None
    app_id: Optional[str] = None
    url: Optional[str] = None


class TraceResult(BaseModel):
    initial_url: str
    device: str
    country: str
    country_label: str
    engine: str  # "scraperapi" | "direct"
    tier: str
    egress_ip: Optional[str] = None
    egress_note: Optional[str] = None
    total_redirects: int
    final_url: Optional[str] = None
    final_status: Optional[int] = None
    final_platform: Optional[Platform] = None
    destination: Optional[Destination] = None
    hops: List[Hop] = []
    screenshot: Optional[str] = None  # data URL when screenshot was requested
    warnings: List[str] = []
    meta: Dict[str, Any] = {}
