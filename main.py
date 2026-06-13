from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # <-- Import the middleware
from core.config import STATIC_DIR
from routers import web_router, api_router

app = FastAPI(title="Pi Wiki")

# --- CORS CONFIGURATION ---
# This tells port 8001 that it is allowed to serve data to port 8000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://192.168.0.174:8000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Assets
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include Modular Routers
app.include_router(web_router.router)
app.include_router(api_router.router)