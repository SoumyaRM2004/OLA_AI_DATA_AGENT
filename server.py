import os
import sys
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from utils.database import DatabaseConnection
from utils.etl_tools import ETLTools
from utils.data_importer import (
    validate_csv_content,
    validate_batch_foreign_keys,
    load_datasets_transactional,
    TABLE_SCHEMAS
)
from agents.data_agent import execute_agent_query

app = FastAPI(
    title="OLA AI Data Agent API",
    description="Multi-Agent AI for OLA Ride-Hailing Analytics & Weather ETL Operations",
    version="1.1.0"
)

# CORS middleware configured for safe local development
allowed_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ------------------- PYDANTIC MODELS -------------------

class ChatRequest(BaseModel):
    message: str

class ExtractRequest(BaseModel):
    url: Optional[str] = "https://archive-api.open-meteo.com/v1/archive?start_date=2025-01-01&end_date=2025-01-31"
    output_format: str = "csv"
    output_folder: str = "data/extract"
    city_name: Optional[str] = "All 8 Cities"
    start_date: Optional[str] = "2025-01-01"
    end_date: Optional[str] = "2025-01-31"

class TransformRequest(BaseModel):
    input_file: str = "data/extract/weather_data.csv"
    user_question: str = "Filter rows where is_rainy is true and calculate total precipitation by city"
    output_format: str = "csv"
    output_folder: str = "data/transform"

class LoadDbRequest(BaseModel):
    file_path: str = "data/extract/weather_data.csv"
    table_name: str = "weather_data"


# ------------------- API ENDPOINTS -------------------

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Main interaction point for the AI Data Agent.
    Routes between SQL Analyst and ETL Analyst.
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    
    result = execute_agent_query(request.message.strip())
    return JSONResponse(content=result)


@app.get("/api/stats")
async def get_stats():
    """
    Fetches database KPIs and aggregated metrics for the overview dashboard.
    """
    db = DatabaseConnection()
    stats = db.get_database_stats()
    return JSONResponse(content=stats)


@app.get("/api/schema")
async def get_schema():
    """
    Fetches schema information, table list, and row counts for all tables (including weather_data).
    """
    db = DatabaseConnection()
    conn = db.get_connection()
    if not conn:
        return JSONResponse(
            status_code=500,
            content={"error": "Database connection is not available. Please check .env credentials."}
        )

    tables = ["users", "vehicles", "rides", "payments", "ratings", "weather_data"]
    schema_data = {}

    for table in tables:
        # Get columns and data types
        col_res = db.execute_query_structured(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = '{table}' AND table_schema = 'public'
            ORDER BY ordinal_position;
        """)
        
        # Get row count
        count_res = db.execute_query_structured(f"SELECT COUNT(*) AS total FROM public.{table};")
        row_count = count_res["records"][0]["total"] if count_res["records"] else 0

        # Sample rows
        sample_res = db.execute_query_structured(f"SELECT * FROM public.{table} LIMIT 3;")

        schema_data[table] = {
            "columns": col_res["records"],
            "row_count": row_count,
            "sample_rows": sample_res["rows"],
            "sample_columns": sample_res["columns"]
        }

    return JSONResponse(content={"tables": schema_data})


@app.get("/api/tables/{table_name}")
async def get_table_content(table_name: str, limit: int = 50, offset: int = 0):
    """
    Returns live table data with pagination limit for the Database Explorer.
    """
    valid_tables = ["users", "vehicles", "rides", "payments", "ratings", "weather_data"]
    if table_name not in valid_tables:
        raise HTTPException(status_code=400, detail=f"Invalid table name '{table_name}'. Choose from {valid_tables}")

    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="Query limit parameter must be between 1 and 500.")

    if offset < 0:
        raise HTTPException(status_code=400, detail="Query offset parameter must be non-negative.")

    db = DatabaseConnection()
    res = db.get_table_data(table_name, limit=limit, offset=offset)
    return JSONResponse(content=res)


@app.post("/api/etl/extract")
async def trigger_extract(request: ExtractRequest):
    """
    Triggers an API extraction (e.g. Open-Meteo Weather for 8 cities or custom API) and saves the file.
    """
    etl = ETLTools()
    
    if (request.city_name and "all" in request.city_name.lower()) or (request.url and ("all" in request.url.lower() or "8" in request.url.lower())):
        msg = etl.extract_multi_city_weather(
            start_date=request.start_date or "2025-01-01",
            end_date=request.end_date or "2025-01-31",
            output_folder=request.output_folder,
            format=request.output_format
        )
    else:
        msg = etl.extract_load(
            url=request.url or "https://api.open-meteo.com/v1/forecast?latitude=43.65&longitude=-79.38&hourly=temperature_2m,precipitation,rain,weather_code",
            output_folder=request.output_folder,
            format=request.output_format,
            city_name=request.city_name
        )
    
    # Check if file was created safely
    try:
        folder_path = etl._resolve_safe_data_path(request.output_folder)
        expected_path = str(folder_path / f"weather_data.{request.output_format.lower()}")
        if not os.path.exists(expected_path):
            expected_path = str(folder_path / f"extracted_data.{request.output_format.lower()}")
    except Exception:
        expected_path = ""

    preview = {}
    if expected_path and os.path.exists(expected_path):
        preview = etl.preview_file(expected_path, max_rows=5)

    return JSONResponse(content={"message": msg, "preview": preview, "file_path": expected_path})


@app.post("/api/etl/transform")
async def trigger_transform(request: TransformRequest):
    """
    Triggers an LLM-assisted transformation on an existing dataset.
    """
    from agents.etl_analyst import transform_load_tool
    msg = transform_load_tool.invoke({
        "input_file_path": request.input_file,
        "output_folder": request.output_folder,
        "output_format": request.output_format,
        "user_question": request.user_question
    })

    etl = ETLTools()
    files = etl.list_files(request.output_folder)

    return JSONResponse(content={"message": msg, "output_files": files})


@app.post("/api/etl/load-db")
async def trigger_load_to_database(request: LoadDbRequest):
    """
    Loads an extracted or transformed CSV dataset into a PostgreSQL table.
    """
    etl = ETLTools()
    res_msg = etl.load_to_database(request.file_path, request.table_name)
    return JSONResponse(content={"message": res_msg})


@app.get("/api/files")
async def list_data_files():
    """
    Lists extracted and transformed files.
    """
    etl = ETLTools()
    files = etl.list_files("data")
    return JSONResponse(content={"files": files})


@app.get("/api/files/preview")
async def preview_file(path: str):
    """
    Previews a data file for the UI.
    """
    etl = ETLTools()
    res = etl.preview_file(path, max_rows=20)
    return JSONResponse(content=res)


# ------------------- DATA IMPORT ENDPOINTS -------------------

class LoadImportRequest(BaseModel):
    tables: Optional[List[str]] = None

@app.get("/api/import/schema-info")
async def get_import_schema_info():
    """Returns metadata about expected columns and foreign keys for the 5 mobility datasets."""
    return JSONResponse(content={"schemas": TABLE_SCHEMAS})


@app.post("/api/import/validate")
async def validate_import_file(
    file: UploadFile = File(...),
    target_table: Optional[str] = Form(None)
):
    """
    Validates an uploaded CSV file against OLA platform schemas.
    Checks columns, duplicate primary keys, null values, and returns preview records.
    """
    file_bytes = await file.read()
    is_valid, df, table_name, errors, warnings = validate_csv_content(
        file_bytes=file_bytes,
        filename=file.filename,
        explicit_table=target_table
    )

    sample_records = []
    columns = []
    row_count = 0

    if df is not None:
        row_count = len(df)
        columns = list(df.columns)
        # Top 5 records for UI table preview
        sample_records = df.head(5).fillna("").to_dict(orient="records")

        # Save to temporary staging directory if valid
        if is_valid and table_name:
            upload_dir = os.path.join(os.path.dirname(__file__), "data", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            staged_path = os.path.join(upload_dir, f"{table_name}_staged.csv")
            df.to_csv(staged_path, index=False)

    return JSONResponse(content={
        "valid": is_valid,
        "filename": file.filename,
        "table_name": table_name,
        "label": TABLE_SCHEMAS.get(table_name, {}).get("label", table_name) if table_name else "Unknown",
        "row_count": row_count,
        "columns": columns,
        "sample_records": sample_records,
        "errors": errors,
        "warnings": warnings
    })


@app.post("/api/import/load")
async def load_staged_imports(request: LoadImportRequest):
    """
    Loads validated and staged CSV datasets into PostgreSQL inside a single transaction.
    """
    upload_dir = os.path.join(os.path.dirname(__file__), "data", "uploads")
    if not os.path.exists(upload_dir):
        raise HTTPException(status_code=400, detail="No staged datasets found to load.")

    # Determine tables to load
    target_tables = request.tables if request.tables else list(TABLE_SCHEMAS.keys())
    datasets: Dict[str, Any] = {}

    import pandas as pd
    for tbl in target_tables:
        staged_path = os.path.join(upload_dir, f"{tbl}_staged.csv")
        if os.path.exists(staged_path):
            try:
                df = pd.read_csv(staged_path)
                datasets[tbl] = df
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to read staged '{tbl}' dataset: {e}")

    if not datasets:
        raise HTTPException(status_code=400, detail="No valid staged datasets selected for database loading.")

    # 1. Validate foreign keys across batch
    fk_valid, fk_errors, fk_warnings = validate_batch_foreign_keys(datasets)
    if not fk_valid:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Foreign key integrity check failed.",
                "errors": fk_errors,
                "warnings": fk_warnings
            }
        )

    # 2. Transactional Load into PostgreSQL
    result = load_datasets_transactional(datasets)
    
    # 3. Clean up staged files on success
    if result.get("success"):
        for tbl in datasets.keys():
            staged_path = os.path.join(upload_dir, f"{tbl}_staged.csv")
            if os.path.exists(staged_path):
                try:
                    os.remove(staged_path)
                except Exception:
                    pass

    return JSONResponse(content=result)


@app.post("/api/import/clear-staged")
async def clear_staged_imports():
    """Clears all staged uploads."""
    upload_dir = os.path.join(os.path.dirname(__file__), "data", "uploads")
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            if f.endswith("_staged.csv"):
                try:
                    os.remove(os.path.join(upload_dir, f))
                except Exception:
                    pass
    return JSONResponse(content={"message": "Staged imports cleared successfully."})


# ------------------- STATIC FILES MOUNTING -------------------

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "css"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "js"), exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "OLA AI Data Agent API is running. Frontend static/index.html is loading."}


if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting OLA AI Data Agent Web Server on http://localhost:8000 ...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
