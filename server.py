import os
import sys
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from utils.database import DatabaseConnection, sanitize_session_id, get_session_schema_name
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

from utils.chat_store import ChatStore

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def extract_session_id(header_val: Optional[str] = None, param_val: Optional[str] = None, body_val: Optional[str] = None) -> Optional[str]:
    """Helper to extract non-empty session identifier from header, query param, or body."""
    for val in [header_val, param_val, body_val]:
        if val and str(val).strip() and str(val).strip().lower() not in ("none", "null", "undefined"):
            return str(val).strip()
    return None


def get_upload_dir(session_id: Optional[str] = None) -> str:
    """Returns the isolated uploads directory for a given session."""
    safe_id = sanitize_session_id(session_id)
    if safe_id:
        path = os.path.join(os.path.dirname(__file__), "data", "uploads", safe_id)
    else:
        path = os.path.join(os.path.dirname(__file__), "data", "uploads", "default")
    os.makedirs(path, exist_ok=True)
    return path


# ------------------- PYDANTIC MODELS -------------------

class ChatRequest(BaseModel):
    message: str
    chat_id: Optional[str] = None
    session_id: Optional[str] = None

class CreateChatRequest(BaseModel):
    title: Optional[str] = "New Chat"
    session_id: Optional[str] = None

class UpdateChatRequest(BaseModel):
    title: str

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

@app.get("/api/chats")
async def list_chats_endpoint(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """Returns list of persistent chat sessions for the active user/session."""
    sid = extract_session_id(x_session_id, session_id)
    chats = ChatStore.list_chats(session_id=sid)
    return JSONResponse(content={"chats": chats})


@app.post("/api/chats")
async def create_chat_endpoint(
    request: Optional[CreateChatRequest] = None,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """Creates a new unique chat session associated with the active session."""
    title = request.title if request and request.title else "New Chat"
    req_sid = request.session_id if request else None
    sid = extract_session_id(x_session_id, req_sid)
    chat = ChatStore.create_chat(title=title, session_id=sid)
    return JSONResponse(content=chat)


@app.get("/api/chats/{chat_id}")
async def get_chat_endpoint(
    chat_id: str,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """Fetches full chat session with message history, isolated by session ownership."""
    sid = extract_session_id(x_session_id, session_id)
    chat = ChatStore.get_chat(chat_id, session_id=sid)
    if not chat:
        raise HTTPException(status_code=404, detail=f"Chat session '{chat_id}' not found.")
    return JSONResponse(content=chat)


@app.put("/api/chats/{chat_id}")
async def update_chat_endpoint(
    chat_id: str,
    request: UpdateChatRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """Renames a specific chat session if owned by the active session."""
    if not request.title or not request.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty.")
    sid = extract_session_id(x_session_id)
    chat = ChatStore.update_chat_title(chat_id, request.title.strip(), session_id=sid)
    if not chat:
        raise HTTPException(status_code=404, detail=f"Chat session '{chat_id}' not found.")
    return JSONResponse(content=chat)


@app.delete("/api/chats/{chat_id}")
async def delete_chat_endpoint(
    chat_id: str,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """Deletes a chat session if owned by the active session."""
    sid = extract_session_id(x_session_id, session_id)
    success = ChatStore.delete_chat(chat_id, session_id=sid)
    if not success:
        raise HTTPException(status_code=404, detail=f"Chat session '{chat_id}' not found.")
    return JSONResponse(content={"success": True, "message": f"Chat session '{chat_id}' deleted."})


@app.post("/api/chats/{chat_id}/clear")
async def clear_chat_endpoint(
    chat_id: str,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """Clears messages for a specific chat session if owned by the active session."""
    sid = extract_session_id(x_session_id, session_id)
    success = ChatStore.clear_messages(chat_id, session_id=sid)
    if not success:
        raise HTTPException(status_code=404, detail=f"Chat session '{chat_id}' not found.")
    return JSONResponse(content={"success": True, "message": "Chat history cleared."})


@app.post("/api/chat")
async def chat_endpoint(
    request: ChatRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """
    Main interaction point for the AI Data Agent.
    Routes between SQL Analyst and ETL Analyst.
    Always executes live query against active session dataset in PostgreSQL.
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    sid = extract_session_id(x_session_id, request.session_id)
    chat_id = request.chat_id
    chat_obj = ChatStore.get_chat(chat_id, session_id=sid) if chat_id else None

    # If chat_id does not exist or belongs to another session, create a new chat for this session
    if not chat_id or not chat_obj:
        new_chat = ChatStore.create_chat(title="New Chat", session_id=sid)
        chat_id = new_chat["id"]
        chat_obj = new_chat
    elif not sid and chat_obj.get("session_id"):
        sid = chat_obj.get("session_id")

    # 1. Record user message in persistent chat session
    ChatStore.add_message(chat_id, role="user", content=request.message.strip(), extra_data={"session_id": sid}, session_id=sid)

    # 2. Execute live agent query against PostgreSQL scoped to active session dataset
    result = execute_agent_query(request.message.strip(), chat_id=chat_id, session_id=sid)

    # 3. Record assistant response in persistent chat session
    ChatStore.add_message(
        chat_id,
        role="assistant",
        content=result.get("answer", ""),
        extra_data=result,
        session_id=sid
    )

    # 4. Attach chat context metadata
    updated_chat = ChatStore.get_chat(chat_id, session_id=sid)
    result["chat_id"] = chat_id
    result["chat_title"] = updated_chat.get("title", "New Chat") if updated_chat else "New Chat"
    result["session_id"] = sid

    return JSONResponse(content=result)


@app.get("/api/stats")
async def get_stats(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """
    Fetches database KPIs and aggregated metrics for the overview dashboard scoped to session dataset.
    """
    sid = extract_session_id(x_session_id, session_id)
    db = DatabaseConnection()
    stats = db.get_database_stats(session_id=sid)
    return JSONResponse(content=stats)


@app.get("/api/schema")
async def get_schema(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """
    Fetches schema information, table list, and row counts scoped to session dataset.
    """
    try:
        sid = extract_session_id(x_session_id, session_id)
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
        session_tables = db.get_session_tables(sid) if sid else set()
        session_schema = get_session_schema_name(sid)

        for table in tables:
            active_schema = session_schema if (session_schema and table in session_tables) else "public"
            target_table_ref = f"{active_schema}.{table}"

            # Get columns and data types
            col_res = db.execute_query_structured(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = '{table}' AND table_schema = '{active_schema}'
                ORDER BY ordinal_position;
            """, session_id=sid)

            # Get row count
            count_res = db.execute_query_structured(f"SELECT COUNT(*) AS total FROM {target_table_ref};", session_id=sid)
            row_count = count_res["records"][0]["total"] if count_res["records"] else 0

            # Sample rows
            sample_res = db.execute_query_structured(f"SELECT * FROM {target_table_ref} LIMIT 3;", session_id=sid)

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
async def get_table_content(
    table_name: str,
    limit: int = 50,
    offset: int = 0,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """
    Returns live table data with pagination limit for the Database Explorer scoped to session dataset.
    """
    valid_tables = ["users", "vehicles", "rides", "payments", "ratings", "weather_data"]
    if table_name not in valid_tables:
        raise HTTPException(status_code=400, detail=f"Invalid table name '{table_name}'. Choose from {valid_tables}")

    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="Query limit parameter must be between 1 and 500.")

    if offset < 0:
        raise HTTPException(status_code=400, detail="Query offset parameter must be non-negative.")

    try:
        sid = extract_session_id(x_session_id, session_id)
        db = DatabaseConnection()
        res = db.get_table_data(table_name, limit=limit, offset=offset, session_id=sid)
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
    session_id: Optional[str] = None

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
    from utils.data_importer import CANONICAL_SAMPLES
    from fastapi.responses import Response
    tbl = dataset_type.lower().strip()
    if tbl not in CANONICAL_SAMPLES:
        raise HTTPException(status_code=404, detail=f"Sample dataset '{tbl}' not found. Supported: {list(CANONICAL_SAMPLES.keys())}")

    csv_text = CANONICAL_SAMPLES[tbl]
    sample_filename = f"{tbl}_sample.csv"
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{sample_filename}"'
        }
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
    default_values: Optional[str] = Form(None),
    import_mode: Optional[str] = Form("upsert"),
    session_id: Optional[str] = Form(None),
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """
    Validates an uploaded CSV file strictly against the selected/detected OLA mobility schema.
    Applies column mappings, normalizes raw values (NaN, NULL, timestamps), checks PKs and FKs,
    and stages the canonical dataset in the session's isolated directory if valid.
    """
    file_bytes = await file.read()
    sid = extract_session_id(x_session_id, session_id)
    
    parsed_custom_mappings = None
    if custom_mappings and custom_mappings.strip():
        try:
            parsed_custom_mappings = json.loads(custom_mappings)
        except Exception:
            parsed_custom_mappings = None

    parsed_default_values = None
    if default_values and default_values.strip():
        try:
            parsed_default_values = json.loads(default_values)
        except Exception:
            parsed_default_values = None

    is_valid, df, table_name, structured_errors, warnings, metadata = validate_csv_content(
        file_bytes=file_bytes,
        filename=file.filename,
        dataset_type=dataset_type,
        custom_mappings=parsed_custom_mappings,
        default_values=parsed_default_values,
        import_mode=import_mode or "upsert"
    )

    sample_records = []
    columns = metadata.get("columns", [])
    row_count = metadata.get("row_count", 0)

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

        # Save normalized data to session-isolated temporary staging directory if valid
        if is_valid and table_name:
            upload_dir = get_upload_dir(sid)
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
        "metadata": metadata,
        "session_id": sid
    })


@app.post("/api/import/load")
async def load_staged_imports(
    request: LoadImportRequest,
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID")
):
    """
    Loads validated and staged CSV datasets into PostgreSQL inside a single atomic transaction.
    Isolates data to the session-specific PostgreSQL schema without touching the base dataset.
    """
    sid = extract_session_id(x_session_id, request.session_id)
    upload_dir = get_upload_dir(sid)
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

    # 1. Validate foreign keys across batch & session/live PostgreSQL
    fk_valid, fk_errors, fk_warnings = validate_batch_foreign_keys(datasets, session_id=sid)
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

    # 2. Transactional Load into PostgreSQL session schema
    result = load_datasets_transactional(datasets, import_mode=request.import_mode or "upsert", session_id=sid)
    
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
async def clear_staged_imports(
    x_session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    session_id: Optional[str] = Query(None)
):
    """Clears all staged uploads for the active session."""
    sid = extract_session_id(x_session_id, session_id)
    upload_dir = get_upload_dir(sid)
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            if f.endswith("_staged.csv"):
                try:
                    os.remove(os.path.join(upload_dir, f))
                except Exception:
                    pass
    return JSONResponse(content={"message": "Staged imports cleared successfully.", "session_id": sid})



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
