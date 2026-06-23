"""
routers/static_routes.py — Routes for serving the React frontend.

Endpoints:
    GET /             → serves static/index.html
    GET /favicon.ico  → 204 No Content
"""

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/")
def home():
    return FileResponse("static/index.html")


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
