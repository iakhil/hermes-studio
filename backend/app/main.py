import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import chat, doctor, gateway, health, setup, tools

app = FastAPI(
    title="Hermes Studio",
    description="The missing GUI for Hermes Agent",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(doctor.router, prefix="/api/v1")
app.include_router(setup.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(gateway.router, prefix="/api/v1")
app.include_router(chat.router)

# Serve frontend static files in production
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
