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
from utils.etl_tools import ETLTools, CITY_COORDINATES, normalize_date_str
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
    try:
        db = DatabaseConnection()
        conn = db.get_connection()
        if not conn:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Database connection is not available. Please check .env credentials.",
                    "tables": {}
                }
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
                "columns": col_res.get("records", []),
                "row_count": row_count,
                "sample_rows": sample_res.get("rows", []),
                "sample_columns": sample_res.get("columns", [])
            }

        return JSONResponse(content={"tables": schema_data, "error": None})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Database schema query error: {str(e)}", "tables": {}}
        )


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

    try:
        db = DatabaseConnection()
        res = db.get_table_data(table_name, limit=limit, offset=offset)
        return JSONResponse(content=res)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "columns": [],
                "rows": [],
                "records": [],
                "error": f"Database query error on table '{table_name}': {str(e)}"
            }
        )


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
        # Check if a specific city was selected from the 8 configured cities
        selected_city = request.city_name if request.city_name and request.city_name in CITY_COORDINATES else None
        if selected_city:
            coords = CITY_COORDINATES[selected_city]
            valid_start, norm_start = normalize_date_str(request.start_date, "2025-01-01")
            valid_end, norm_end = normalize_date_str(request.end_date, "2025-01-31")
            if not valid_start:
                msg = f"Date Validation Error: {norm_start}"
            elif not valid_end:
                msg = f"Date Validation Error: {norm_end}"
            elif norm_start > norm_end:
                msg = f"Date Validation Error: Start date ({norm_start}) cannot be after end date ({norm_end})."
            else:
                city_url = (
                    f"https://archive-api.open-meteo.com/v1/archive?"
                    f"latitude={coords['latitude']}&longitude={coords['longitude']}&"
                    f"start_date={norm_start}&end_date={norm_end}&"
                    f"hourly=temperature_2m,precipitation,rain,weather_code"
                )
                msg = etl.extract_load(
                    url=city_url,
                    output_folder=request.output_folder,
                    format=request.output_format,
                    city_name=selected_city
                )
        else:
            msg = etl.extract_load(
                url=request.url or "https://api.open-meteo.com/v1/forecast?latitude=43.65&longitude=-79.38&hourly=temperature_2m,precipitation,rain,weather_code",
                output_folder=request.output_folder,
                format=request.output_format,
                city_name=request.city_name
            )
    
    # Check if extraction resulted in error
    is_error = any(msg.startswith(prefix) for prefix in [
        "Error", "API request failed", "API returned an empty", "API returned an unexpected",
        "API Network Error", "API connection error", "API request timed out", "API request error",
        "Date Validation Error", "Filesystem Security Error", "Security Validation Error",
        "URL Security Error", "Coordinate Error"
    ])
    
    if is_error:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": msg, "message": msg}
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

    return JSONResponse(content={"success": True, "message": msg, "preview": preview, "file_path": expected_path})


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


import io
import json
import math
from datetime import datetime, date
from decimal import Decimal
import pandas as pd
import numpy as np

def serialize_dict_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean_records = []
    for r in records:
        clean_r = {}
        for k, v in r.items():
            if v is None:
                clean_r[k] = ""
            elif isinstance(v, (datetime, date, pd.Timestamp)):
                clean_r[k] = str(v)
            elif isinstance(v, (Decimal, float, np.floating)):
                clean_r[k] = float(v) if not (math.isnan(v) or math.isinf(v)) else ""
            elif isinstance(v, (int, np.integer)):
                clean_r[k] = int(v)
            elif isinstance(v, (bool, np.bool_)):
                clean_r[k] = bool(v)
            else:
                clean_r[k] = str(v)
        clean_records.append(clean_r)
    return clean_records

class LoadImportRequest(BaseModel):
    tables: Optional[List[str]] = None
    import_mode: Optional[str] = "upsert"

@app.get("/api/import/schema-info")
async def get_import_schema_info():
    """Returns metadata about expected columns, data types, aliases, and foreign keys for the 5 mobility datasets."""
    from utils.data_importer import COLUMN_ALIASES
    return JSONResponse(content={
        "schemas": TABLE_SCHEMAS,
        "aliases": COLUMN_ALIASES
    })


@app.get("/api/import/samples/{dataset_type}")
async def get_sample_csv(dataset_type: str):
    """
    Returns the canonical, pre-validated sample CSV file for the requested dataset.
    """
    tbl = dataset_type.lower().strip()
    valid_tables = ["users", "vehicles", "rides", "payments", "ratings"]
    if tbl not in valid_tables:
        raise HTTPException(status_code=404, detail=f"Sample dataset '{tbl}' not found. Supported: {valid_tables}")

    sample_filename = f"{tbl}_sample.csv"
    sample_path = os.path.join(os.path.dirname(__file__), "data", "sample", sample_filename)
    if not os.path.exists(sample_path):
        sample_path = os.path.join(os.path.dirname(__file__), "tests", "fixtures", f"valid_{tbl}.csv")

    if not os.path.exists(sample_path):
        raise HTTPException(status_code=404, detail=f"Sample file for '{tbl}' not found.")

    return FileResponse(
        path=sample_path,
        media_type="text/csv",
        filename=sample_filename
    )


@app.post("/api/import/inspect")
async def inspect_import_file(
    file: UploadFile = File(...),
    dataset_type: Optional[str] = Form(None)
):
    """
    Fast inspection of uploaded CSV headers to auto-detect dataset type and propose column mappings.
    """
    from utils.data_importer import detect_dataset_from_headers, map_columns_to_schema
    file_bytes = await file.read()
    
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(status_code=400, content={"error": f"'{file.filename}' is not a valid CSV file."})
    
    try:
        raw_df = pd.read_csv(io.BytesIO(file_bytes), nrows=10, dtype=object)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Failed to parse CSV: {str(e)}"})

    uploaded_cols = list(raw_df.columns)
    
    # Auto-detection
    target = dataset_type.lower().strip() if dataset_type and dataset_type.strip() not in ("", "auto", "auto_detect") else None
    detection = detect_dataset_from_headers(uploaded_cols)
    detected_table = target or detection.get("detected_dataset")
    
    mapping_info = {}
    if detected_table and detected_table in TABLE_SCHEMAS:
        mapping_info = map_columns_to_schema(uploaded_cols, detected_table)

    sample_preview = serialize_dict_records(raw_df.head(3).to_dict(orient="records"))

    return JSONResponse(content={
        "filename": file.filename,
        "uploaded_columns": uploaded_cols,
        "detected_dataset": detected_table,
        "label": TABLE_SCHEMAS.get(detected_table, {}).get("label", "Unknown") if detected_table else "Unknown",
        "confidence": detection.get("confidence", "Low"),
        "confidence_score": detection.get("confidence_score", 0.0),
        "proposed_mappings": mapping_info.get("mapped_columns", {}),
        "mapping_details": mapping_info.get("mapping_details", []),
        "extra_columns": mapping_info.get("extra_columns", []),
        "missing_required": mapping_info.get("missing_required", []),
        "all_scores": detection.get("all_scores", {}),
        "sample_preview": sample_preview
    })


@app.post("/api/import/validate")
async def validate_import_file(
    file: UploadFile = File(...),
    dataset_type: str = Form(...),
    custom_mappings: Optional[str] = Form(None),
    import_mode: Optional[str] = Form("upsert")
):
    """
    Validates an uploaded CSV file strictly against the selected/detected OLA mobility schema.
    Applies column mappings, normalizes raw values (NaN, NULL, timestamps), checks PKs and FKs,
    and stages the canonical dataset if valid.
    """
    file_bytes = await file.read()
    
    parsed_custom_mappings = None
    if custom_mappings and custom_mappings.strip():
        try:
            parsed_custom_mappings = json.loads(custom_mappings)
        except Exception:
            parsed_custom_mappings = None

    is_valid, df, table_name, structured_errors, warnings, metadata = validate_csv_content(
        file_bytes=file_bytes,
        filename=file.filename,
        dataset_type=dataset_type,
        custom_mappings=parsed_custom_mappings,
        import_mode=import_mode or "upsert"
    )

    sample_records = []
    columns = []
    row_count = 0

    # Format text error strings for display compatibility
    text_errors = [
        err["problem"] if isinstance(err, dict) and "problem" in err else str(err)
        for err in structured_errors
    ]

    if df is not None and not df.empty:
        row_count = len(df)
        columns = list(df.columns)
        # Top 10 records for UI table preview with safe serialization
        sample_records = serialize_dict_records(df.head(10).to_dict(orient="records"))

        # Save normalized data to temporary staging directory if valid
        if is_valid and table_name:
            upload_dir = os.path.join(os.path.dirname(__file__), "data", "uploads")
            os.makedirs(upload_dir, exist_ok=True)
            staged_path = os.path.join(upload_dir, f"{table_name}_staged.csv")
            df.to_csv(staged_path, index=False)

    return JSONResponse(content={
        "valid": is_valid,
        "validation_state": metadata.get("validation_state", "VALID" if is_valid else "INVALID"),
        "filename": file.filename,
        "table_name": table_name,
        "label": TABLE_SCHEMAS.get(table_name, {}).get("label", table_name) if table_name else "Unknown",
        "row_count": row_count,
        "columns": columns,
        "sample_records": sample_records,
        "structured_errors": structured_errors,
        "errors": text_errors,
        "warnings": warnings,
        "metadata": metadata
    })


@app.post("/api/import/load")
async def load_staged_imports(request: LoadImportRequest):
    """
    Loads validated and staged CSV datasets into PostgreSQL inside a single atomic transaction.
    If any table fails, the transaction is rolled back immediately.
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

    # 1. Validate foreign keys across batch & live PostgreSQL
    fk_valid, fk_errors, fk_warnings = validate_batch_foreign_keys(datasets)
    if not fk_valid:
        text_fk_errors = [
            err["problem"] if isinstance(err, dict) and "problem" in err else str(err)
            for err in fk_errors
        ]
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Foreign key integrity check failed.",
                "structured_errors": fk_errors,
                "errors": text_fk_errors,
                "warnings": fk_warnings
            }
        )

    # 2. Transactional Load into PostgreSQL
    result = load_datasets_transactional(datasets, import_mode=request.import_mode or "upsert")
    
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
