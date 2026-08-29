import os
import io
import sys
import requests
import pandas as pd
from typing import Dict, Any, Optional


class ETLTools:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def _resolve_path(self, folder_or_file: str) -> str:
        """Resolves path relative to project root if not absolute."""
        if os.path.isabs(folder_or_file):
            return folder_or_file
        return os.path.join(self.project_root, folder_or_file)

    def extract_load(self, url: str, output_folder: str = "data/extract", format: str = "csv") -> str:
        """
        Extracts data from the given API (URL) and loads it into the desired location.
        
        Args:
            url: The URL of the API from which data is to be extracted.
            output_folder: The folder path where the extracted data is saved.
            format: 'csv', 'json', or 'parquet'.
            
        Returns:
            str: A message indicating the success or failure of the operation.
        """
        resolved_folder = self._resolve_path(output_folder)
        os.makedirs(resolved_folder, exist_ok=True)
        filename = os.path.join(resolved_folder, f"extracted_data.{format.lower()}")

        try:
            headers = {"User-Agent": "OLA-AI-DataAgent/1.0"}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Flexible parsing for various JSON API responses
            if isinstance(data, list):
                df = pd.json_normalize(data)
            elif isinstance(data, dict):
                if "results" in data and isinstance(data["results"], list):
                    df = pd.json_normalize(data["results"])
                elif "data" in data and isinstance(data["data"], list):
                    df = pd.json_normalize(data["data"])
                elif "items" in data and isinstance(data["items"], list):
                    df = pd.json_normalize(data["items"])
                else:
                    # Flatten the dictionary
                    df = pd.json_normalize(data)
            else:
                return f"Error: Unexpected API response format: {type(data)}"

            fmt = format.lower()
            if fmt == "csv":
                df.to_csv(filename, index=False)
            elif fmt == "json":
                df.to_json(filename, orient="records", indent=2)
            elif fmt == "parquet":
                df.to_parquet(filename, index=False)
            else:
                return f"Error: Unsupported format '{format}'. Supported formats: csv, json, parquet."

            return (
                f"Successfully extracted {len(df)} records from {url}.\n"
                f"Saved to: {filename}\n"
                f"Columns: {', '.join(df.columns[:10])}{'...' if len(df.columns) > 10 else ''}"
            )

        except Exception as e:
            return f"Error in extracting data: {e}"

    def transform_load_context(self, file_path: str) -> str:
        """
        Reads sample rows from the file to provide context for code generation.
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

            info_str = f"Columns: {list(df.columns)}\nShape: {df.shape}\n\nTop 3 Sample Rows:\n{df.head(3).to_string()}"
            return info_str

        except Exception as e:
            return f"Error loading file context: {e}"

    def execute_code(self, code: str) -> str:
        """
        Executes the generated Python/Pandas code safely while capturing stdout.
        """
        # Capture print outputs
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

    def list_files(self, folder: str = "data") -> list:
        """Lists files in extract or transform folders with sizes and row counts for UI."""
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
        """Returns structured rows and columns from a CSV/JSON/Parquet file for UI table rendering."""
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

            preview_df = df.head(max_rows)
            # Fill NaN values with empty string for JSON serialization
            preview_df = preview_df.fillna("")
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
    print("ETLTools initialized successfully.")
    print("Files found:", obj.list_files("data"))
