import os
import csv
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()

if "port" not in os.environ:
    os.environ["port"] = "5432"

# ============================================================
# CONFIGURATION
# ============================================================

DB_CONFIG = {
    "host": os.environ["host"],
    "port": int(os.environ["port"]),
    "database": os.environ["database"],
    "user": os.environ["user"],
    "password": os.environ["password"],
}

CSV_DIR = "data"


# ============================================================
# DATABASE CONNECTION
# ============================================================

conn = psycopg2.connect(**DB_CONFIG)
conn.autocommit = False

cursor = conn.cursor()

print("Connected to PostgreSQL")


# ============================================================
# CREATE TABLES
# ============================================================

create_tables_sql = """

CREATE SCHEMA IF NOT EXISTS public;

-- =========================================================
-- USERS
-- =========================================================

CREATE TABLE IF NOT EXISTS public.users (
    user_id INTEGER PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    city VARCHAR(100),
    province VARCHAR(50),
    user_type VARCHAR(20) NOT NULL,
    signup_date DATE,
    is_active BOOLEAN
);


-- =========================================================
-- VEHICLES
-- =========================================================

CREATE TABLE IF NOT EXISTS public.vehicles (
    vehicle_id INTEGER PRIMARY KEY,
    driver_id INTEGER NOT NULL,
    make VARCHAR(50),
    model VARCHAR(50),
    year INTEGER,
    license_plate VARCHAR(20) UNIQUE,
    color VARCHAR(30),
    is_active BOOLEAN,

    CONSTRAINT fk_vehicle_driver
        FOREIGN KEY (driver_id)
        REFERENCES public.users(user_id)
);


-- =========================================================
-- RIDES
-- =========================================================

CREATE TABLE IF NOT EXISTS public.rides (
    ride_id INTEGER PRIMARY KEY,

    rider_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,
    vehicle_id INTEGER,

    pickup_latitude DECIMAL(9,6),
    pickup_longitude DECIMAL(9,6),
    dropoff_latitude DECIMAL(9,6),
    dropoff_longitude DECIMAL(9,6),

    requested_at TIMESTAMP,
    pickup_time TIMESTAMP,
    dropoff_time TIMESTAMP,

    fare DECIMAL(10,2),
    distance_km DECIMAL(6,2),
    duration_minutes DECIMAL(6,2),

    surge_multiplier DECIMAL(3,2),

    status VARCHAR(30),
    cancellation_reason VARCHAR(100),

    CONSTRAINT fk_ride_rider
        FOREIGN KEY (rider_id)
        REFERENCES public.users(user_id),

    CONSTRAINT fk_ride_driver
        FOREIGN KEY (driver_id)
        REFERENCES public.users(user_id),

    CONSTRAINT fk_ride_vehicle
        FOREIGN KEY (vehicle_id)
        REFERENCES public.vehicles(vehicle_id)
);


-- =========================================================
-- PAYMENTS
-- =========================================================

CREATE TABLE IF NOT EXISTS public.payments (
    payment_id INTEGER PRIMARY KEY,

    ride_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,

    amount DECIMAL(10,2),

    payment_method VARCHAR(50),
    payment_status VARCHAR(30),

    transaction_id VARCHAR(100) UNIQUE,
    payment_time TIMESTAMP,

    CONSTRAINT fk_payment_ride
        FOREIGN KEY (ride_id)
        REFERENCES public.rides(ride_id),

    CONSTRAINT fk_payment_user
        FOREIGN KEY (user_id)
        REFERENCES public.users(user_id)
);


-- =========================================================
-- RATINGS
-- =========================================================

CREATE TABLE IF NOT EXISTS public.ratings (
    rating_id INTEGER PRIMARY KEY,

    ride_id INTEGER NOT NULL,
    rider_id INTEGER NOT NULL,
    driver_id INTEGER NOT NULL,

    rating INTEGER,
    comment TEXT,
    rated_at TIMESTAMP,

    CONSTRAINT fk_rating_ride
        FOREIGN KEY (ride_id)
        REFERENCES public.rides(ride_id),

    CONSTRAINT fk_rating_rider
        FOREIGN KEY (rider_id)
        REFERENCES public.users(user_id),

    CONSTRAINT fk_rating_driver
        FOREIGN KEY (driver_id)
        REFERENCES public.users(user_id),

    CONSTRAINT chk_rating
        CHECK (rating BETWEEN 1 AND 5)
);


-- =========================================================
-- WEATHER DATA (8 RIDE-HAILING CITIES CONTEXTUAL ENRICHMENT)
-- =========================================================

CREATE TABLE IF NOT EXISTS public.weather_data (
    weather_id SERIAL PRIMARY KEY,
    recorded_at TIMESTAMP NOT NULL,
    city VARCHAR(100) NOT NULL,
    latitude DECIMAL(9,6),
    longitude DECIMAL(9,6),
    temperature_c DECIMAL(5,2),
    precipitation_mm DECIMAL(6,2),
    rain_mm DECIMAL(6,2),
    weather_code INTEGER,
    is_rainy BOOLEAN
);


-- =========================================================
-- INDEXES & CONSTRAINTS
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_vehicles_driver_id ON public.vehicles(driver_id);
CREATE INDEX IF NOT EXISTS idx_rides_rider_id ON public.rides(rider_id);
CREATE INDEX IF NOT EXISTS idx_rides_driver_id ON public.rides(driver_id);
CREATE INDEX IF NOT EXISTS idx_rides_requested_at ON public.rides(requested_at);
CREATE INDEX IF NOT EXISTS idx_rides_status ON public.rides(status);
CREATE INDEX IF NOT EXISTS idx_payments_ride_id ON public.payments(ride_id);
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON public.payments(user_id);
CREATE INDEX IF NOT EXISTS idx_ratings_ride_id ON public.ratings(ride_id);
CREATE INDEX IF NOT EXISTS idx_ratings_driver_id ON public.ratings(driver_id);
CREATE INDEX IF NOT EXISTS idx_weather_recorded_at ON public.weather_data(recorded_at);
CREATE INDEX IF NOT EXISTS idx_weather_city ON public.weather_data(city);
CREATE UNIQUE INDEX IF NOT EXISTS uq_weather_city_recorded ON public.weather_data(city, recorded_at);

"""

cursor.execute(create_tables_sql)
print("Tables created successfully")


# ============================================================
# CSV LOADING FUNCTION WITH HEADER REORDERING
# ============================================================

def load_csv(table_name, file_path, target_columns):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    print(f"\nLoading data into {table_name} from {file_path} ...")

    # Clean table before load for idempotency
    cursor.execute(sql.SQL("TRUNCATE TABLE {}.{} CASCADE;").format(
        sql.Identifier("public"),
        sql.Identifier(table_name)
    ))

    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        header_index = {col: idx for idx, col in enumerate(header)}

        # Validate that all required target columns are present
        missing = [c for c in target_columns if c not in header_index]
        if missing:
            print(f"Error: Missing columns in {file_path}: {missing}")
            return

        copy_sql = sql.SQL(
            "COPY {}.{} ({}) FROM STDIN WITH (FORMAT csv, NULL '')"
        ).format(
            sql.Identifier("public"),
            sql.Identifier(table_name),
            sql.SQL(", ").join(map(sql.Identifier, target_columns)),
        )

        copy_cursor = cursor.connection.cursor()
        
        # Generator that yields CSV lines in target_column order
        def row_generator():
            for row in reader:
                ordered_row = [row[header_index[col]] for col in target_columns]
                yield "\t".join(ordered_row) + "\n"

        import io
        buf = io.StringIO()
        for row in reader:
            ordered = []
            for col in target_columns:
                val = row[header_index[col]].strip()
                if val == "" or val.lower() == "null":
                    ordered.append("")
                else:
                    # Escape quotes if present
                    escaped_val = val.replace('"', '""')
                    ordered.append(f'"{escaped_val}"')
            buf.write(",".join(ordered) + "\n")

        buf.seek(0)
        copy_cursor.copy_expert(
            sql.SQL("COPY {}.{} ({}) FROM STDIN WITH (FORMAT csv, QUOTE '\"', NULL '')").format(
                sql.Identifier("public"),
                sql.Identifier(table_name),
                sql.SQL(", ").join(map(sql.Identifier, target_columns)),
            ).as_string(conn),
            buf
        )
        copy_cursor.close()

    print(f"Successfully loaded {table_name}")


# ============================================================
# LOAD CORE RIDE DATASETS
# ============================================================

# USERS
load_csv(
    "users",
    os.path.join(CSV_DIR, "users.csv"),
    [
        "user_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "city",
        "province",
        "user_type",
        "signup_date",
        "is_active",
    ],
)

# VEHICLES
load_csv(
    "vehicles",
    os.path.join(CSV_DIR, "vehicles.csv"),
    [
        "vehicle_id",
        "driver_id",
        "make",
        "model",
        "year",
        "license_plate",
        "color",
        "is_active",
    ],
)

# RIDES
load_csv(
    "rides",
    os.path.join(CSV_DIR, "rides.csv"),
    [
        "ride_id",
        "rider_id",
        "driver_id",
        "pickup_latitude",
        "pickup_longitude",
        "dropoff_latitude",
        "dropoff_longitude",
        "requested_at",
        "pickup_time",
        "dropoff_time",
        "fare",
        "distance_km",
        "surge_multiplier",
        "status",
        "cancellation_reason",
    ],
)

# PAYMENTS
load_csv(
    "payments",
    os.path.join(CSV_DIR, "payments.csv"),
    [
        "payment_id",
        "ride_id",
        "user_id",
        "amount",
        "payment_method",
        "payment_status",
        "transaction_id",
        "payment_time",
    ],
)

# RATINGS
load_csv(
    "ratings",
    os.path.join(CSV_DIR, "ratings.csv"),
    [
        "rating_id",
        "ride_id",
        "rider_id",
        "driver_id",
        "rating",
        "comment",
        "rated_at",
    ],
)


# ============================================================
# LOAD WEATHER DATA (ALL 8 CITIES)
# ============================================================

weather_csv_path = os.path.join(CSV_DIR, "extract", "weather_data.csv")
if not os.path.exists(weather_csv_path):
    print("Extracting 8-city weather dataset from Open-Meteo...")
    from utils.etl_tools import ETLTools
    ETLTools().extract_multi_city_weather()

load_csv(
    "weather_data",
    weather_csv_path,
    [
        "recorded_at",
        "city",
        "latitude",
        "longitude",
        "temperature_c",
        "precipitation_mm",
        "rain_mm",
        "weather_code",
        "is_rainy",
    ],
)


# ============================================================
# VERIFY RECORD COUNTS & CITY BREAKDOWN
# ============================================================

tables = [
    "users",
    "vehicles",
    "rides",
    "payments",
    "ratings",
    "weather_data",
]

print("\nRecord counts:")
print("-" * 40)

for table in tables:
    cursor.execute(
        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            sql.Identifier("public"),
            sql.Identifier(table)
        )
    )
    count = cursor.fetchone()[0]
    print(f"{table:<15} {count:>10,}")

print("\nWeather Cities Breakdown:")
cursor.execute("SELECT city, COUNT(*), MIN(recorded_at)::date, MAX(recorded_at)::date FROM public.weather_data GROUP BY city ORDER BY city;")
for row in cursor.fetchall():
    print(f"  {row[0]:<12}: {row[1]} records ({row[2]} to {row[3]})")


# ============================================================
# COMMIT & CLOSE
# ============================================================

conn.commit()
print("\nData loaded successfully! Transaction committed.")

cursor.close()
conn.close()
print("PostgreSQL connection closed.")