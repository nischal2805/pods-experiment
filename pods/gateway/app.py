from fastapi import FastAPI

from .dashboard import router as dashboard_router
from .routes_external import router as external_router
from .routes_internal import router as internal_router

app = FastAPI(title="Pods Gateway", version="1.0.0")
app.include_router(external_router)
app.include_router(internal_router)
app.include_router(dashboard_router)
