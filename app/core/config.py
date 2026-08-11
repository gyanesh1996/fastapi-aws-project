from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "Redirect Tracer"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api"

    # --- ScraperAPI proxy configuration -------------------------------------
    # Set SCRAPERAPI_KEY in the environment (or .env) to enable real
    # residential/geo egress. When empty, the tracer runs in "direct" mode,
    # which works for open links but will be blocked (403) by ad networks.
    SCRAPERAPI_KEY: str = ""
    SCRAPERAPI_PROXY_HOST: str = "proxy-server.scraperapi.com"
    SCRAPERAPI_PROXY_PORT: int = 8001

    # Proxy tier strategy for each hop:
    #   "auto"    -> try datacenter (1 credit), escalate to premium/ultra on block
    #   "basic"   -> datacenter proxies only (cheapest, usually 403s on ad links)
    #   "premium" -> residential proxies (10 credits/hop)
    #   "ultra"   -> ultra_premium anti-bot bypass (30 credits/hop)
    PROXY_TIER: str = "auto"

    # Follow JavaScript / SDK redirects that plain HTTP tracing can't resolve by
    # re-fetching the stalled hop through ScraperAPI's headless browser (render).
    ENABLE_RENDER_ESCALATION: bool = True

    # Trace limits and timeouts (seconds).
    MAX_HOPS: int = 25
    REQUEST_TIMEOUT: float = 40.0
    RENDER_TIMEOUT: float = 80.0

    # Max characters of a response body kept for inspection / redirect parsing.
    BODY_SNIPPET_LIMIT: int = 4000

    @property
    def scraperapi_enabled(self) -> bool:
        return bool(self.SCRAPERAPI_KEY.strip())


settings = Settings()
