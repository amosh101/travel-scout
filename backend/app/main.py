from contextlib import asynccontextmanager
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.routers import auth, interests, alerts, notifications, recommendations
from app.middleware.request_id import request_id_middleware  # MVP Revamp 2026-06-25

logger = logging.getLogger(__name__)

try:
    from app.routers import neural_search
    NEURAL_ROUTER_AVAILABLE = True
except ImportError:
    NEURAL_ROUTER_AVAILABLE = False

# Initialize rate limiter (60 requests per minute per IP)
limiter = Limiter(key_func=get_remote_address)
request_log: dict = {}

def log_request(request: Request):
    """Log request for monitoring"""
    client_ip = get_remote_address(request)
    timestamp = time.time()
    endpoint = request.url.path
    rid = getattr(request.state, "request_id", "no-rid")
    logger.info(f"[{time.strftime('%H:%M:%S')}] rid={rid} {client_ip} → {endpoint}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database tables
    await init_db()
    logger.info("Travel Scout API started — request_id middleware active")
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Travel Scout API",
    description="Flight and event alert system",
    version="0.2.0",  # bumped for MVP Revamp 2026-06-25
    lifespan=lifespan,
)

# MVP Revamp 2026-06-25: request_id middleware MUST be first so every
# downstream middleware/handler can read request.state.request_id and
# the response header always carries it.
app.middleware("http")(request_id_middleware)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request logging middleware (after request_id so log lines carry rid)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    log_request(request)
    response = await call_next(request)
    return response

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://100.115.184.82:3004",
        "http://100.115.184.82:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(interests.router)
app.include_router(alerts.router)
app.include_router(notifications.router)
app.include_router(recommendations.router)

# MVP Revamp 2026-06-25: GDPR account endpoints (delete, export, audit history)
from app.routers import account  # noqa: E402
app.include_router(account.router)

# Include neural search router if available
if NEURAL_ROUTER_AVAILABLE:
    app.include_router(neural_search.router)
    logger.info("✓ Neural search router enabled")
else:
    logger.warning("⚠ Neural search router not available")


@app.get("/")
async def root():
    return {"message": "Travel Scout API", "version": "0.2.0"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "neural_search": NEURAL_ROUTER_AVAILABLE,
        "request_id_middleware": True,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )