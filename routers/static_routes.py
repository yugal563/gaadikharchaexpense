"""
routers/static_routes.py — Routes for serving the React frontend and static files.

Endpoints:
    GET /             → serves the React app's index.html
    GET /favicon.ico  → serves the favicon, if present in static/
    GET /static/*     → serves other static assets (JS, CSS, etc.)
"""

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

router = APIRouter()

# Serve the main React app
@router.get("/", response_class=HTMLResponse)
async def serve_react_app():
    return FileResponse("static/index.html")

# This will serve files like favicon.ico, main.js, main.css from the static directory
if os.path.exists("static"):
    router.mount("/static", StaticFiles(directory="static"), name="static")
