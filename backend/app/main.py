from contextlib import asynccontextmanager
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.routers import auth, interests, alerts, notifications, recommendations

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
    print(f"[{time.strftime('%H:%M:%S')}] {client_ip} → {endpoint}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database tables
    await init_db()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Travel Scout API",
    description="Flight and event alert system",
    version="0.1.0",
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Request logging middleware
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

# Include neural search router if available
if NEURAL_ROUTER_AVAILABLE:
    app.include_router(neural_search.router)
    print("✓ Neural search router enabled")
else:
    print("⚠ Neural search router not available")


@app.get("/")
async def root():
    return {"message": "Travel Scout API", "version": "0.1.0"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "neural_search": NEURAL_ROUTER_AVAILABLE
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )