from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router as agent_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Multi-Agent Business Assistant API for Market, Finance, Report, and Orchestration.",
)

# Enable CORS for external frontends and dev environments (allow all origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes directly and under api prefix
app.include_router(agent_router)
app.include_router(agent_router, prefix=settings.API_PREFIX)


@app.get("/")
def root():
    """Root endpoint for quick service check."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "health_url": "/health",
        "endpoints": [
            "/agents/finance",
            "/agents/market",
            "/agents/report",
            "/orchestrate"
        ]
    }


@app.get("/health")
def health_check():
    """Health check endpoint returning exact required status ok."""
    return {"status": "ok"}
