from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from core.config import STATIC_DIR
from routers import web_router, api_router

app = FastAPI(title="Pi Wiki")

# Mount Static Assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include Modular Routers
app.include_router(web_router.router)
app.include_router(api_router.router)