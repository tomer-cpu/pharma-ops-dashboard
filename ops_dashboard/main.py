import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from ops_dashboard.config import STATIC_DIR
from ops_dashboard.data.database import init_db
from ops_dashboard.data.mock_generator import seed_mock_data
from ops_dashboard.api import quality, service, cost, efficiency, risk, summary, filters, settings
from ops_dashboard.retail_price_monitor import api as retail_price_api
from ops_dashboard.retail_price_monitor.database import init_db as init_rpm_db
from ops_dashboard.retail_price_monitor.mock_generator import seed_mock_data as seed_rpm_mock
from ops_dashboard.retail_price_monitor.analytics import generate_alerts_for_date


# -- Embedding middleware -------------------------------------------------
# Allows tzeelon.com (and any subdomain) to embed this dashboard in an iframe.

EMBED_ALLOWED_ORIGINS = [
    "https://www.tzeelon.com",
    "https://tzeelon.com",
    "https://*.tzeelon.com",
]


class EmbedMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        csp_ancestors = " ".join(EMBED_ALLOWED_ORIGINS)
        response.headers["Content-Security-Policy"] = (
            f"frame-ancestors 'self' {csp_ancestors}"
        )
        if "X-Frame-Options" in response.headers:
            del response.headers["X-Frame-Options"]
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seeded = seed_mock_data()
    if seeded:
        print("  Mock data seeded successfully (9,000+ records)")
    else:
        print("  Database already contains data")

    # Retail price monitor (Leiman Schlissel) ----------------------------
    init_rpm_db()
    if seed_rpm_mock():
        print("  Retail price monitor seeded with mock observations")
    else:
        print("  Retail price monitor already contains observations")
    # Always (re)build alerts for the latest snapshot so the dashboard has
    # fresh rollups on startup.
    generate_alerts_for_date(None)
    yield


app = FastAPI(
    title="Pharma Operational Metrics API",
    description="REST API for pharmaceutical operational metrics - Quality, Service & Cost KPIs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(EmbedMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(quality.router, prefix="/api/quality", tags=["Quality"])
app.include_router(service.router, prefix="/api/service", tags=["Service"])
app.include_router(cost.router, prefix="/api/cost", tags=["Cost"])
app.include_router(efficiency.router, prefix="/api/efficiency", tags=["Efficiency"])
app.include_router(risk.router, prefix="/api/risk", tags=["Risk"])
app.include_router(summary.router, prefix="/api/summary", tags=["Summary"])
app.include_router(filters.router, prefix="/api/filters", tags=["Filters"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(retail_price_api.router, prefix="/api/retail-price", tags=["Retail Price Monitor"])

# Serve frontend static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/embed")
async def embed():
    """Embeddable version - cleaner layout without header/footer."""
    return FileResponse(os.path.join(STATIC_DIR, "embed.html"))


@app.get("/retail-price")
async def retail_price_dashboard():
    """Hebrew RTL dashboard for the Leiman Schlissel retail price monitor."""
    return FileResponse(os.path.join(STATIC_DIR, "retail_price", "index.html"))
