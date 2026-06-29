"""
main.py — FastAPI application entry point.

All business logic is modularized:
    models.py                    → Custom model (Expense)
    services/db.py               → DB connection provider (get_connection)
    services/db_service.py       → DB persistence (insert_expense, save_expenses_to_db)
    pipeline/                    → Stagewise receipt scanning pipeline, schemas, prompt logic & image utilities
    services/llm_providers.py    → Multi-provider LLM abstraction layer
    routers/static_routes.py     → GET /, GET /favicon.ico
    routers/scan_routes.py       → POST /scan-receipt, /scan-receipt-debug
    routers/expense_routes.py    → POST/GET/DELETE /expenses, GET /expenses/category/{cat}
"""

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from routers import expense_routes, scan_routes, static_routes, async_scan_routes

# ─────────────────────────────────────────────
#  App setup
# ─────────────────────────────────────────────
app = FastAPI(title="Vehicle Expense Tracker API")

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print("[FastAPI Validation Error]:", exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ─────────────────────────────────────────────
#  Routers
# ─────────────────────────────────────────────
app.include_router(static_routes.router)
app.include_router(scan_routes.router)
app.include_router(expense_routes.router)
app.include_router(async_scan_routes.router)

# ─────────────────────────────────────────────
#  Swagger UI — force file upload for list[UploadFile]
# ─────────────────────────────────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Receipt Scanner API",
        version="1.0.0",
        routes=app.routes,
    )
    for path in openapi_schema.get("paths", {}).values():
        for method in path.values():
            if "requestBody" in method:
                content = method["requestBody"].get("content", {})
                if "multipart/form-data" in content:
                    schema = content["multipart/form-data"].get("schema", {})
                    if "$ref" in schema:
                        ref_name = schema["$ref"].split("/")[-1]
                        schema = openapi_schema["components"]["schemas"][ref_name]
                    properties = schema.get("properties", {})
                    for prop_val in properties.values():
                        if prop_val.get("type") == "array" and prop_val.get("items", {}).get("type") == "string":
                            prop_val["items"]["format"] = "binary"
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
