import os
import io
import sys
import ast
import ipaddress
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import requests
import pandas as pd
import numpy as np
from utils.database import DatabaseConnection

# ============================================================
# CENTRALIZED 8-CITY COORDINATE CONFIGURATION
# Coordinates correspond to official city centers for OLA ride-hailing cities
# ============================================================

CITY_COORDINATES: Dict[str, Dict[str, Any]] = {
    "Calgary": {"latitude": 51.0447, "longitude": -114.0719, "province": "AB"},
    "Edmonton": {"latitude": 53.5461, "longitude": -113.4938, "province": "AB"},
    "Halifax": {"latitude": 44.6488, "longitude": -63.5752, "province": "NS"},
    "Montreal": {"latitude": 45.5017, "longitude": -73.5673, "province": "QC"},
    "Ottawa": {"latitude": 45.4215, "longitude": -75.6972, "province": "ON"},
    "Toronto": {"latitude": 43.6532, "longitude": -79.3832, "province": "ON"},
    "Vancouver": {"latitude": 49.2827, "longitude": -123.1207, "province": "BC"},
    "Winnipeg": {"latitude": 49.8951, "longitude": -97.1384, "province": "MB"},
}

# ============================================================
# AST SECURITY VALIDATOR FOR PYTHON TRANSFORMATION SCRIPTS
# Rejects dangerous calls, imports, dunders, and OS-level operations
# ============================================================

DANGEROUS_CALLS = {
    "open", "eval", "exec", "__import__", "compile", "globals", "locals",
    "getattr", "setattr", "delattr", "hasattr", "breakpoint", "exit", "quit",
    "input", "help", "system", "popen", "spawn", "fork", "kill", "remove",
    "unlink", "rmdir", "makedirs", "rename", "replace", "chmod", "chown"
}

DANGEROUS_NAMES = {
    "os", "sys", "subprocess", "shutil", "socket", "requests", "urllib",
    "pathlib", "pty", "posix", "builtins", "__builtins__", "pickle", "ctypes",
    "importlib", "gc", "inspect"
}

DANGEROUS_ATTRS = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__builtins__",
    "__code__", "__class__", "__dict__", "__module__", "__qualname__",
    "to_sql", "to_pickle", "read_pickle", "to_clipboard", "read_clipboard"
}

SAFE_BUILTINS: Dict[str, Any] = {
    "len": len,
    "range": range,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "print": print,
    "isinstance": isinstance,
    "enumerate": enumerate,
    "zip": zip,
    "sorted": sorted,
    "reversed": reversed,
    "any": any,
    "all": all,
    "None": None,
    "True": True,
    "False": False,
}


def validate_python_ast(code: str) -> Tuple[bool, str]:
    """
    Parses Python code into an Abstract Syntax Tree (AST) and strictly validates
    that no dangerous operations (imports, system commands, file deletion, dunder probing)
    are present.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Python Syntax Error in generated code: {e}"

    for node in ast.walk(tree):
        # 1. Reject import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "Import statements are disallowed in transformation scripts."

        # 2. Reject dangerous function / method calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_CALLS:
                return False, f"Disallowed function call detected: '{node.func.id}()'"
            elif isinstance(node.func, ast.Attribute) and node.func.attr in DANGEROUS_CALLS:
                return False, f"Disallowed method call detected: '{node.func.attr}()'"

        # 3. Reject references to dangerous modules or built-in namespaces
        if isinstance(node, ast.Name) and node.id in DANGEROUS_NAMES:
            return False, f"Disallowed module/identifier access: '{node.id}'"

        # 4. Reject access to dangerous internal attributes (dunder traversal)
        if isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ATTRS:
            return False, f"Disallowed attribute access: '{node.attr}'"

    return True, ""


# ============================================================
# ETL TOOLS CLASS
# ============================================================

class ETLTools:
    def __init__(self):
        self.project_root = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))).resolve()
        self.data_dir = (self.project_root / "data").resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_data_path(self, folder_or_file: str, allow_root_data: bool = True) -> Path:
        """
        Safely resolves a path and guarantees it resides strictly inside the project's data/ directory.
        Prevents directory traversal attacks (e.g. ../../etc/passwd).
        """
        target = Path(folder_or_file)
        if target.is_absolute():
            resolved = target.resolve()
        else:
            resolved = (self.project_root / target).resolve()

        # Verify that resolved path is inside data_dir
        try:
            resolved.relative_to(self.data_dir)
        except ValueError:
            raise PermissionError(
                f"Security Violation: Path '{folder_or_file}' resolves outside the permitted data directory ('{self.data_dir}')."
            )

        return resolved

    def _validate_safe_url(self, url: str) -> Tuple[bool, str]:
        """
        Validates external API URL against Server-Side Request Forgery (SSRF).
        Rejects internal addresses, private IPs, localhost, and non-HTTP protocols.
        """
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception as e:
            return False, f"Invalid URL structure: {e}"

        if parsed.scheme not in ("http", "https"):
            return False, f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False, "URL must include a valid hostname."

        # Block localhost and loopbacks
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"):
            return False, "Access to localhost/loopback addresses is prohibited."

        if hostname.endswith((".local", ".internal", ".localhost", ".lan")):
            return False, "Access to internal domain zones is prohibited."

        # Check for private IP addresses
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False, f"Access to private/internal IP address '{hostname}' is prohibited."
        except ValueError:
            # Hostname is a domain name, which is allowed
            pass

        return True, ""

    def extract_multi_city_weather(
        self,
        start_date: str = "2025-01-01",
        end_date: str = "2025-01-31",
        output_folder: str = "data/extract",
        format: str = "csv"
    ) -> str:
        """
        Extracts hourly historical weather data for all 8 ride-hailing cities from Open-Meteo Archive API
        and consolidates them into a single dataset within data/extract.
        """
        try:
            resolved_folder = self._resolve_safe_data_path(output_folder)
            resolved_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Filesystem Security Error: {e}"

        headers = {"User-Agent": "OLA-AI-DataAgent/1.0"}
        dfs = []
        city_summaries = []

        try:
            for city, coords in CITY_COORDINATES.items():
                lat = coords["latitude"]
                lon = coords["longitude"]
                url = (
                    f"https://archive-api.open-meteo.com/v1/archive?"
                    f"latitude={lat}&longitude={lon}&start_date={start_date}&end_date={end_date}&"
                    f"hourly=temperature_2m,precipitation,rain,weather_code"
                )

                # Validate URL before making request
                is_safe, url_err = self._validate_safe_url(url)
                if not is_safe:
                    return f"URL Security Error: {url_err}"

                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()

                if "hourly" not in data or "time" not in data["hourly"]:
                    continue

                hourly = data["hourly"]
                df = pd.DataFrame(hourly)
                df.rename(columns={
                    "time": "recorded_at",
                    "temperature_2m": "temperature_c",
                    "precipitation": "precipitation_mm",
                    "rain": "rain_mm",
                    "weather_code": "weather_code"
                }, inplace=True)

                df["latitude"] = lat
                df["longitude"] = lon
                df["city"] = city
                df["is_rainy"] = (df["rain_mm"] > 0.0) | (df["precipitation_mm"] > 0.0)

                dfs.append(df)
                city_summaries.append(f"• {city}: {len(df)} hrs ({df['is_rainy'].sum()} rainy/precip hrs)")

            if not dfs:
                return "Error: No weather data could be extracted from Open-Meteo."

            final_df = pd.concat(dfs, ignore_index=True)

            cols = [
                "recorded_at", "city", "latitude", "longitude",
                "temperature_c", "precipitation_mm", "rain_mm",
                "weather_code", "is_rainy"
            ]
            final_df = final_df[cols]

            fmt = format.lower().strip()
            filename = resolved_folder / f"weather_data.{fmt}"

            if fmt == "csv":
                final_df.to_csv(filename, index=False)
            elif fmt == "json":
                final_df.to_json(filename, orient="records", indent=2)
            elif fmt == "parquet":
                final_df.to_parquet(filename, index=False)
            else:
                return f"Error: Unsupported format '{format}' (permitted: csv, json, parquet)"

            return (
                f"Successfully extracted weather data for all 8 ride-hailing cities ({len(final_df)} total records).\n"
                f"Saved to: {filename}\n"
                f"Date Range: {start_date} to {end_date}\n\n"
                f"City Breakdown:\n" + "\n".join(city_summaries)
            )

        except requests.exceptions.RequestException as e:
            return f"API Network Error: {e}"
        except Exception as e:
            return f"Error during multi-city extraction: {e}"

    def extract_load(
        self,
        url: str,
        output_folder: str = "data/extract",
        format: str = "csv",
        city_name: Optional[str] = None
    ) -> str:
        """
        Extracts data from a validated external API endpoint into the local data directory.
        """
        # Validate SSRF safety
        is_safe, err_msg = self._validate_safe_url(url)
        if not is_safe:
            return f"Security Validation Error: {err_msg}"

        try:
            resolved_folder = self._resolve_safe_data_path(output_folder)
            resolved_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Filesystem Security Error: {e}"

        # If user requests all cities or weather without specific coords, run multi-city extraction
        if "all" in url.lower() or "8" in url.lower():
            return self.extract_multi_city_weather(output_folder=output_folder, format=format)

        try:
            headers = {"User-Agent": "OLA-AI-DataAgent/1.0"}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Specialized handling for Open-Meteo Weather API structure
            if isinstance(data, dict) and "hourly" in data and isinstance(data["hourly"], dict) and "time" in data["hourly"]:
                hourly = data["hourly"]
                df = pd.DataFrame(hourly)

                rename_map = {
                    "time": "recorded_at",
                    "temperature_2m": "temperature_c",
                    "precipitation": "precipitation_mm",
                    "rain": "rain_mm",
                    "weather_code": "weather_code"
                }
                df.rename(columns=rename_map, inplace=True)

                lat = data.get("latitude")
                lon = data.get("longitude")
                df["latitude"] = lat
                df["longitude"] = lon

                if not city_name:
                    city_name = "Toronto"
                    if lat and lon:
                        for c_name, c_coords in CITY_COORDINATES.items():
                            if abs(lat - c_coords["latitude"]) < 1.0 and abs(lon - c_coords["longitude"]) < 1.0:
                                city_name = c_name
                                break

                df["city"] = city_name
                df["is_rainy"] = (df.get("rain_mm", 0) > 0.0) | (df.get("precipitation_mm", 0) > 0.0)
                base_filename = "weather_data"

            elif isinstance(data, list):
                df = pd.json_normalize(data)
                base_filename = "extracted_data"
            elif isinstance(data, dict):
                if "results" in data and isinstance(data["results"], list):
                    df = pd.json_normalize(data["results"])
                elif "data" in data and isinstance(data["data"], list):
                    df = pd.json_normalize(data["data"])
                elif "items" in data and isinstance(data["items"], list):
                    df = pd.json_normalize(data["items"])
                else:
                    df = pd.json_normalize(data)
                base_filename = "extracted_data"
            else:
                return f"Error: Unsupported JSON response structure: {type(data)}"

            fmt = format.lower().strip()
            filename = resolved_folder / f"{base_filename}.{fmt}"

            if fmt == "csv":
                df.to_csv(filename, index=False)
            elif fmt == "json":
                df.to_json(filename, orient="records", indent=2)
            elif fmt == "parquet":
                df.to_parquet(filename, index=False)
            else:
                return f"Error: Unsupported format '{format}'"

            return (
                f"Successfully extracted {len(df)} records from API.\n"
                f"Saved to: {filename}\n"
                f"Columns: {', '.join(list(df.columns)[:8])}\n"
                f"Date Range: {df['recorded_at'].min() if 'recorded_at' in df.columns else 'N/A'} to "
                f"{df['recorded_at'].max() if 'recorded_at' in df.columns else 'N/A'}"
            )

        except requests.exceptions.RequestException as e:
            return f"API Network Error: {e}"
        except Exception as e:
            return f"Error during data extraction: {e}"

    def transform_load_context(self, file_path: str) -> str:
        """
        Reads sample rows from a local dataset within data/ to provide context for Pandas code generation.
        """
        try:
            resolved_path = self._resolve_safe_data_path(file_path)
        except Exception as e:
            return f"Security Error: {e}"

        if not resolved_path.exists():
            return f"Error: File not found at {resolved_path}"

        file_extension = resolved_path.suffix.lower()
        try:
            if file_extension == ".csv":
                df = pd.read_csv(resolved_path)
            elif file_extension == ".json":
                df = pd.read_json(resolved_path)
            elif file_extension == ".parquet":
                df = pd.read_parquet(resolved_path)
            else:
                return f"Error: Unsupported file format '{file_extension}'"

            info_str = (
                f"Columns: {list(df.columns)}\n"
                f"Shape: {df.shape}\n"
                f"Distinct Cities: {df['city'].unique().tolist() if 'city' in df.columns else 'N/A'}\n\n"
                f"Top 3 Sample Rows:\n{df.head(3).to_string()}"
            )
            return info_str

        except Exception as e:
            return f"Error reading file context: {e}"

    def execute_code(self, code: str) -> str:
        """
        Executes Python/Pandas transformation script in a restricted sandbox environment
        after validating the code AST for dangerous operations.
        """
        # 1. Clean markdown code fences if present
        cleaned_code = code.strip()
        if cleaned_code.startswith("```python"):
            cleaned_code = cleaned_code[9:]
        elif cleaned_code.startswith("```"):
            cleaned_code = cleaned_code[3:]
        if cleaned_code.endswith("```"):
            cleaned_code = cleaned_code[:-3]
        cleaned_code = cleaned_code.strip()

        # 2. Strict AST Security Validation
        is_valid, err_msg = validate_python_ast(cleaned_code)
        if not is_valid:
            return f"Security Validation Error: {err_msg}"

        # 3. Restricted Execution Environment
        captured_stdout = io.StringIO()
        old_stdout = sys.stdout

        # Restricted execution scope (no os, sys, subprocess, open, or unrestricted builtins)
        restricted_globals = {
            "__builtins__": SAFE_BUILTINS,
            "pd": pd,
            "np": np,
        }
        restricted_locals: Dict[str, Any] = {}

        try:
            sys.stdout = captured_stdout
            exec(cleaned_code, restricted_globals, restricted_locals)
            output = captured_stdout.getvalue()
            return f"Code executed successfully.\nOutput:\n{output}" if output else "Code executed successfully."
        except Exception as e:
            return f"Execution Error: {e}"
        finally:
            sys.stdout = old_stdout

    def load_to_database(self, file_path: str = "data/extract/weather_data.csv", table_name: str = "weather_data") -> str:
        """
        Loads a CSV/JSON/Parquet dataset from data/ into PostgreSQL with duplicate prevention.
        """
        try:
            resolved_path = self._resolve_safe_data_path(file_path)
        except Exception as e:
            return f"Security Error: {e}"

        if not resolved_path.exists():
            return f"Error: File {file_path} not found."

        try:
            ext = resolved_path.suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(resolved_path)
            elif ext == ".json":
                df = pd.read_json(resolved_path)
            elif ext == ".parquet":
                df = pd.read_parquet(resolved_path)
            else:
                return f"Error: Unsupported format {ext}"

            db = DatabaseConnection()
            res = db.load_dataframe(df, table_name=table_name)
            if res.get("success"):
                return f"Successfully loaded {res['rows_inserted']} rows from {file_path} into public.{table_name}."
            else:
                return f"Database load error: {res.get('error')}"

        except Exception as e:
            return f"Error loading to database: {e}"

    def list_files(self, folder: str = "data") -> list:
        """Lists files strictly within the data/ directory for the UI."""
        try:
            resolved_folder = self._resolve_safe_data_path(folder)
        except Exception:
            return []

        if not resolved_folder.exists():
            return []

        results = []
        for root, _, files in os.walk(resolved_folder):
            for file in files:
                if file.endswith((".csv", ".json", ".parquet")):
                    path = Path(root) / file
                    try:
                        rel_path = path.relative_to(self.project_root)
                        size_kb = round(path.stat().st_size / 1024, 2)
                        results.append({
                            "filename": file,
                            "relative_path": str(rel_path).replace("\\", "/"),
                            "full_path": str(path).replace("\\", "/"),
                            "size_kb": size_kb
                        })
                    except Exception:
                        continue
        return results

    def preview_file(self, file_path: str, max_rows: int = 10) -> Dict[str, Any]:
        """Returns structured rows and columns from a dataset strictly inside data/."""
        try:
            resolved = self._resolve_safe_data_path(file_path)
        except Exception as e:
            return {"error": f"Security Error: {e}", "columns": [], "rows": []}

        if not resolved.exists():
            return {"error": f"File {file_path} not found", "columns": [], "rows": []}

        try:
            ext = resolved.suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(resolved)
            elif ext == ".json":
                df = pd.read_json(resolved)
            elif ext == ".parquet":
                df = pd.read_parquet(resolved)
            else:
                return {"error": f"Unsupported format {ext}", "columns": [], "rows": []}

            preview_df = df.head(max_rows).fillna("")
            return {
                "columns": list(preview_df.columns),
                "rows": preview_df.values.tolist(),
                "records": preview_df.to_dict(orient="records"),
                "total_rows": len(df),
                "shape": df.shape,
                "cities": df["city"].unique().tolist() if "city" in df.columns else [],
                "error": None
            }
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": []}


if __name__ == "__main__":
    tools = ETLTools()
    print("Testing 8-City Weather Extraction...")
    res = tools.extract_multi_city_weather()
    print(res)
