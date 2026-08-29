import os
import io
import sys
import requests
import pandas as pd
from typing import Dict, Any, Optional
from utils.database import DatabaseConnection


class ETLTools:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _resolve_path(self, folder_or_file: str) -> str:
        """Resolves path relative to project root if not absolute."""
        if os.path.isabs(folder_or_file):
            return folder_or_file
        return os.path.join(self.project_root, folder_or_file)

    def extract_load(
        self,
        url: str,
        output_folder: str = "data/extract",
        format: str = "csv",
        city_name: Optional[str] = None
    ) -> str:
        """
        Extracts data from an external REST API (e.g., Open-Meteo Weather API or generic JSON endpoint)
        and loads it into the desired location.
        
        Args:
            url: The API URL endpoint.
            output_folder: Directory to save the extracted file (default: data/extract).
            format: 'csv', 'json', or 'parquet'.
            city_name: Optional city tag for location-based weather datasets.
            
        Returns:
            str: Summary of extraction status, record count, and output path.
        """
        resolved_folder = self._resolve_path(output_folder)
        os.makedirs(resolved_folder, exist_ok=True)

        try:
            headers = {"User-Agent": "OLA-AI-DataAgent/1.0"}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            # 1. Specialized handling for Open-Meteo Weather API structure
            if isinstance(data, dict) and "hourly" in data and isinstance(data["hourly"], dict) and "time" in data["hourly"]:
                hourly = data["hourly"]
                df = pd.DataFrame(hourly)

                # Rename columns for standard schema
                rename_map = {
                    "time": "recorded_at",
                    "temperature_2m": "temperature_c",
                    "precipitation": "precipitation_mm",
                    "rain": "rain_mm",
                    "weather_code": "weather_code"
                }
                df.rename(columns=rename_map, inplace=True)

                # Add location metadata
                lat = data.get("latitude")
                lon = data.get("longitude")
                df["latitude"] = lat
                df["longitude"] = lon

                # Derive city name if not provided
                if not city_name:
                    if lat and lon:
                        if 43.0 <= lat <= 44.5 and -80.5 <= lon <= -78.5:
                            city_name = "Toronto"
                        elif 45.0 <= lat <= 46.0 and -74.5 <= lon <= -73.0:
                            city_name = "Montreal"
                        elif 44.0 <= lat <= 45.5 and -64.5 <= lon <= -63.0:
                            city_name = "Halifax"
                        elif 45.0 <= lat <= 45.8 and -76.5 <= lon <= -75.0:
                            city_name = "Ottawa"
                        elif 12.8 <= lat <= 13.2 and 77.4 <= lon <= 77.8:
                            city_name = "Bengaluru"
                        else:
                            city_name = f"Region ({lat:.2f}, {lon:.2f})"
                    else:
                        city_name = "Metro Region"

                df["city"] = city_name

                # Ensure rain_mm / precipitation_mm exist
                if "rain_mm" not in df.columns and "precipitation_mm" in df.columns:
                    df["rain_mm"] = df["precipitation_mm"]
                elif "precipitation_mm" not in df.columns and "rain_mm" in df.columns:
                    df["precipitation_mm"] = df["rain_mm"]

                # Boolean indicator for rain
                rain_col = df["rain_mm"] if "rain_mm" in df.columns else df.get("precipitation_mm", 0)
                df["is_rainy"] = rain_col > 0.0

                base_filename = "weather_data"

            # 2. Generic API normalization for other datasets
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

            # Save in requested format
            fmt = format.lower()
            filename = os.path.join(resolved_folder, f"{base_filename}.{fmt}")

            if fmt == "csv":
                df.to_csv(filename, index=False)
            elif fmt == "json":
                df.to_json(filename, orient="records", indent=2)
            elif fmt == "parquet":
                df.to_parquet(filename, index=False)
            else:
                return f"Error: Unsupported format '{format}'. Supported formats: csv, json, parquet."

            return (
                f"Successfully extracted {len(df)} records from API.\n"
                f"Saved to: {filename}\n"
                f"Columns: {', '.join(list(df.columns)[:8])}{'...' if len(df.columns) > 8 else ''}\n"
                f"Date Range: {df['recorded_at'].min() if 'recorded_at' in df.columns else 'N/A'} to "
                f"{df['recorded_at'].max() if 'recorded_at' in df.columns else 'N/A'}"
            )

        except requests.exceptions.RequestException as e:
            return f"API Network Error: {e}"
        except Exception as e:
            return f"Error during data extraction: {e}"

    def transform_load_context(self, file_path: str) -> str:
        """
        Reads sample rows from a local dataset to provide context for Pandas code generation.
        """
        resolved_path = self._resolve_path(file_path)
        if not os.path.exists(resolved_path):
            return f"Error: File not found at {resolved_path}"

        file_extension = os.path.splitext(resolved_path)[1].lower()
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
                f"Shape: {df.shape}\n\n"
                f"Top 3 Sample Rows:\n{df.head(3).to_string()}"
            )
            return info_str

        except Exception as e:
            return f"Error reading file context: {e}"

    def execute_code(self, code: str) -> str:
        """
        Executes Python/Pandas transformation script safely while capturing standard output.
        """
        captured_stdout = io.StringIO()
        old_stdout = sys.stdout

        local_vars = {"pd": pd, "os": os}

        try:
            sys.stdout = captured_stdout
            exec(code, globals(), local_vars)
            output = captured_stdout.getvalue()
            return f"Code executed successfully.\nOutput:\n{output}" if output else "Code executed successfully."
        except Exception as e:
            return f"Execution Error: {e}"
        finally:
            sys.stdout = old_stdout

    def load_to_database(self, file_path: str, table_name: str = "weather_data") -> str:
        """
        Loads an extracted/transformed CSV dataset directly into PostgreSQL.
        """
        resolved_path = self._resolve_path(file_path)
        if not os.path.exists(resolved_path):
            return f"Error: File {file_path} not found."

        try:
            ext = os.path.splitext(resolved_path)[1].lower()
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
        """Lists files in extract or transform folders with sizes and paths for UI."""
        resolved_folder = self._resolve_path(folder)
        if not os.path.exists(resolved_folder):
            return []

        results = []
        for root, _, files in os.walk(resolved_folder):
            for file in files:
                if file.endswith((".csv", ".json", ".parquet")):
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, self.project_root)
                    size_kb = round(os.path.getsize(path) / 1024, 2)
                    results.append({
                        "filename": file,
                        "relative_path": rel_path,
                        "full_path": path,
                        "size_kb": size_kb
                    })
        return results

    def preview_file(self, file_path: str, max_rows: int = 10) -> Dict[str, Any]:
        """Returns structured rows and columns from a dataset for UI preview."""
        resolved = self._resolve_path(file_path)
        if not os.path.exists(resolved):
            return {"error": f"File {file_path} not found", "columns": [], "rows": []}

        try:
            ext = os.path.splitext(resolved)[1].lower()
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
                "error": None
            }
        except Exception as e:
            return {"error": str(e), "columns": [], "rows": []}


if __name__ == "__main__":
    obj = ETLTools()
    print("Testing Open-Meteo extraction...")
    res = obj.extract_load(
        url="https://api.open-meteo.com/v1/forecast?latitude=43.65&longitude=-79.38&hourly=temperature_2m,precipitation,rain,weather_code",
        output_folder="data/extract",
        format="csv",
        city_name="Toronto"
    )
    print(res)
