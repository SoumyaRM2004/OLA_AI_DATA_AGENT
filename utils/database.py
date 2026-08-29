import os
import psycopg2
from psycopg2 import sql
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()


def get_db_config() -> Dict[str, Any]:
    """Helper to get database connection configuration from environment variables."""
    return {
        "host": os.getenv("host", "localhost"),
        "port": int(os.getenv("port", 5432)),
        "dbname": os.getenv("database", "postgres"),
        "user": os.getenv("user", "postgres"),
        "password": os.getenv("password", ""),
    }


class DatabaseConnection:
    def __init__(self, db_config: Optional[Dict[str, Any]] = None):
        self.db_config = db_config or get_db_config()
        self.connection = None
        self._connect()

    def _connect(self):
        try:
            self.connection = psycopg2.connect(**self.db_config)
        except Exception as e:
            print(f"Error connecting to database: {e}")
            self.connection = None

    def get_connection(self):
        """Returns a valid connection, reconnecting if closed."""
        try:
            if self.connection is None or self.connection.closed != 0:
                self._connect()
        except Exception:
            self._connect()
        return self.connection

    def schema_details(self, schema_name: str = "public") -> str:
        """Fetches detailed schema information including tables, columns, data types, and sample data."""
        connection = self.get_connection()
        if not connection:
            return "Error: Database connection is not available."

        schema_info_context = f"Database Schema : {schema_name}\n"
        cursor = None

        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name;",
                (schema_name,)
            )
            table_list = cursor.fetchall()

            for table in table_list:
                table_name = table[0]
                schema_info_context += f"\nTable: {table_name}\n"

                cursor.execute(
                    "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s AND table_schema = %s ORDER BY ordinal_position;",
                    (table_name, schema_name)
                )
                column_list = cursor.fetchall()

                for column in column_list:
                    column_name = column[0]
                    data_type = column[1]
                    schema_info_context += f"  Column: {column_name}, Data Type: {data_type}\n"

                # Safely fetch sample rows using sql.Identifier
                sample_query = sql.SQL("SELECT * FROM {}.{} LIMIT 3").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name)
                )
                cursor.execute(sample_query)
                sample_data = cursor.fetchall()

                schema_info_context += f"  Sample Data ({len(sample_data)} rows):\n"
                for row in sample_data:
                    schema_info_context += f"    {row}\n"

        except Exception as e:
            print(f"Error in fetching schema details: {e}")
            schema_info_context = f"Error fetching schema details: {e}"
        finally:
            if cursor:
                cursor.close()

        return schema_info_context

    def execute_query(self, query: str) -> str:
        """Executes a query and returns stringified results for the LLM."""
        res = self.execute_query_structured(query)
        if res["error"]:
            return f"SQL execution error: {res['error']}"
        return res["raw_text"]

    def execute_query_structured(self, query: str) -> Dict[str, Any]:
        """
        Executes an SQL query and returns column names, rows, structured dicts,
        and raw string formatting for visualization and charting.
        """
        connection = self.get_connection()
        if not connection:
            return {
                "columns": [],
                "rows": [],
                "records": [],
                "raw_text": "Error: Database connection failed.",
                "row_count": 0,
                "error": "Database connection not available."
            }

        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute(query)

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                raw_rows = cursor.fetchall()

                # Convert non-serializable objects (like datetime, Decimal) to standard JSON types
                rows = []
                records = []
                for row in raw_rows:
                    clean_row = []
                    row_dict = {}
                    for col, val in zip(columns, row):
                        if hasattr(val, "isoformat"):
                            val_clean = val.isoformat()
                        elif hasattr(val, "__float__") and not isinstance(val, (int, float, bool)):
                            val_clean = float(val)
                        else:
                            val_clean = val
                        clean_row.append(val_clean)
                        row_dict[col] = val_clean
                    rows.append(clean_row)
                    records.append(row_dict)

                connection.commit()

                return {
                    "columns": columns,
                    "rows": rows,
                    "records": records,
                    "raw_text": str(raw_rows),
                    "row_count": len(rows),
                    "error": None
                }
            else:
                connection.commit()
                return {
                    "columns": [],
                    "rows": [],
                    "records": [],
                    "raw_text": "Query executed successfully (no rows returned).",
                    "row_count": 0,
                    "error": None
                }

        except Exception as e:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass
            print(f"Error Executing query: {e}")
            return {
                "columns": [],
                "rows": [],
                "records": [],
                "raw_text": f"SQL execution error: {e}",
                "row_count": 0,
                "error": str(e)
            }
        finally:
            if cursor:
                cursor.close()

    def get_table_data(self, table_name: str, limit: int = 50) -> Dict[str, Any]:
        """Fetches table columns and rows for Database Explorer."""
        query = f"SELECT * FROM public.{table_name} LIMIT {limit};"
        return self.execute_query_structured(query)

    def get_database_stats(self) -> Dict[str, Any]:
        """Fetches high-level metrics for dashboard cards and charts."""
        stats = {
            "total_rides": 0,
            "total_users": 0,
            "total_vehicles": 0,
            "total_revenue": 0.0,
            "avg_rating": 0.0,
            "completed_rides": 0,
            "payment_breakdown": [],
            "rides_by_status": [],
            "top_drivers": []
        }

        try:
            # Total users
            res = self.execute_query_structured("SELECT COUNT(*) AS total FROM public.users;")
            if res["records"]:
                stats["total_users"] = res["records"][0].get("total", 0)

            # Total rides & completed rides
            res = self.execute_query_structured("SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed FROM public.rides;")
            if res["records"]:
                stats["total_rides"] = res["records"][0].get("total", 0)
                stats["completed_rides"] = res["records"][0].get("completed", 0)

            # Total vehicles
            res = self.execute_query_structured("SELECT COUNT(*) AS total FROM public.vehicles;")
            if res["records"]:
                stats["total_vehicles"] = res["records"][0].get("total", 0)

            # Total revenue
            res = self.execute_query_structured("SELECT COALESCE(SUM(amount), 0) AS revenue FROM public.payments WHERE payment_status = 'successful' OR payment_status = 'completed';")
            if res["records"]:
                stats["total_revenue"] = float(res["records"][0].get("revenue", 0))

            # Average rating
            res = self.execute_query_structured("SELECT COALESCE(AVG(rating), 0) AS avg_rating FROM public.ratings;")
            if res["records"]:
                stats["avg_rating"] = round(float(res["records"][0].get("avg_rating", 0)), 2)

            # Payment breakdown
            res = self.execute_query_structured("SELECT payment_method, COUNT(*) AS count, SUM(amount) AS total FROM public.payments GROUP BY payment_method ORDER BY count DESC;")
            stats["payment_breakdown"] = res["records"]

            # Rides by status
            res = self.execute_query_structured("SELECT status, COUNT(*) AS count FROM public.rides GROUP BY status ORDER BY count DESC;")
            stats["rides_by_status"] = res["records"]

            # Top 5 drivers
            res = self.execute_query_structured("""
                SELECT u.first_name || ' ' || u.last_name AS driver_name,
                       ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
                       COUNT(r.rating_id) AS total_reviews
                FROM public.ratings r
                JOIN public.users u ON r.driver_id = u.user_id
                GROUP BY u.user_id, u.first_name, u.last_name
                HAVING COUNT(r.rating_id) >= 3
                ORDER BY avg_rating DESC, total_reviews DESC
                LIMIT 5;
            """)
            stats["top_drivers"] = res["records"]

        except Exception as e:
            print(f"Error fetching database stats: {e}")

        return stats


if __name__ == "__main__":
    obj = DatabaseConnection()
    result = obj.schema_details("public")
    print("Schema Details Length:", len(result))
    stats = obj.get_database_stats()
    print("Database Stats:", stats)
