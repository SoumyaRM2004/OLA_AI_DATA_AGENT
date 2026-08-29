import os
import io
import sys
import requests
import pandas as pd
from typing import Dict, Any, Optional, List
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


class ETLTools:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _resolve_path(self, folder_or_file: str) -> str:
        """Resolves path relative to project root if not absolute."""
        if os.path.isabs(folder_or_file):
            return folder_or_file
        return os.path.join(self.project_root, folder_or_file)

    def extract_multi_city_weather(
        self,
        start_date: str = "2025-01-01",
        end_date: str = "2025-01-31",
        output_folder: str = "data/extract",
        format: str = "csv"
    ) -> str:
        """
        Extracts hourly historical weather data for all 8 ride-hailing cities from Open-Meteo Archive API
        and consolidates them into a single dataset.
        
        Args:
            start_date: Start date in YYYY-MM-DD format (default: 2025-01-01).
            end_date: End date in YYYY-MM-DD format (default: 2025-01-31).
            output_folder: Directory to save the extracted dataset.
            format: 'csv', 'json', or 'parquet'.
            
        Returns:
            str: Summary of extraction status and statistics.
        """
        resolved_folder = self._resolve_path(output_folder)
        os.makedirs(resolved_folder, exist_ok=True)

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

            # Standard column ordering
            cols = [
                "recorded_at", "city", "latitude", "longitude",
                "temperature_c", "precipitation_mm", "rain_mm",
                "weather_code", "is_rainy"
            ]
            final_df = final_df[cols]

            fmt = format.lower()
            filename = os.path.join(resolved_folder, f"weather_data.{fmt}")

            if fmt == "csv":
                final_df.to_csv(filename, index=False)
            elif fmt == "json":
                final_df.to_json(filename, orient="records", indent=2)
            elif fmt == "parquet":
                final_df.to_parquet(filename, index=False)
            else:
                return f"Error: Unsupported format '{format}'"

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
        Extracts data from an arbitrary API endpoint or single weather URL.
        """
        resolved_folder = self._resolve_path(output_folder)
        os.makedirs(resolved_folder, exist_ok=True)

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

            # Generic API normalization for other datasets
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

            fmt = format.lower()
            filename = os.path.join(resolved_folder, f"{base_filename}.{fmt}")

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
                f"Shape: {df.shape}\n"
                f"Distinct Cities: {df['city'].unique().tolist() if 'city' in df.columns else 'N/A'}\n\n"
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

    def load_to_database(self, file_path: str = "data/extract/weather_data.csv", table_name: str = "weather_data") -> str:
        """
        Loads an extracted/transformed CSV dataset directly into PostgreSQL with duplicate prevention.
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
