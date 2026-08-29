# 🚗 OLA AI Data Agent

An AI-powered, multi-agent analytics and ETL platform for **OLA-inspired ride-hailing data** — built with **LangGraph**, **FastAPI**, **PostgreSQL**, and a modern **HTML5/CSS3/JavaScript** interactive visual dashboard.

Ask questions in plain English, and the agent automatically routes your request to specialized sub-agents:
- **SQL Analyst** — Natural language to PostgreSQL queries with deterministic syntax validation, an automated **"LLM as Judge"** security audit, auto-generated interactive charts (Bar, Line, Doughnut), and exportable data tables.
- **ETL Analyst** — Extracts external hourly weather data across all **8 Canadian ride-hailing cities** from the **Open-Meteo Archive API**, transforms datasets using Pandas, and loads them into PostgreSQL with duplicate prevention.

> ℹ️ **Dataset Note**: The ride-hailing data used in this project is an **OLA-inspired synthetic dataset** modeled for realistic mobility analytics (rides, drivers, vehicles, payments, ratings). The external Open-Meteo weather integration demonstrates how a modern AI data platform enriches mobility operations with external contextual data across multiple metropolitan regions.

![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_AI-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Modern_Web-teal?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue?logo=postgresql)
![Open-Meteo](https://img.shields.io/badge/Open--Meteo-Weather_API-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🌟 Interactive Web Dashboard

The application includes a dark-themed glassmorphism web interface featuring:

1. **AI Chat Studio**: Interactive conversation, suggested query chips, agent execution timeline (Router &rarr; Question Curation &rarr; SQL Generation &rarr; Security Judge &rarr; Execution), with **auto-generated Chart.js visualizations** and searchable tables.
2. **Analytics KPI Dashboard**: Live KPI cards (total rides, completed rides, total revenue, average driver ratings, 8-city weather coverage) with breakdown charts.
3. **Database Explorer**: Live schema inspector, table data viewer, search/filtering, and row counts across all 6 tables (`users`, `vehicles`, `rides`, `payments`, `ratings`, `weather_data`).
4. **Weather ETL Studio**: Visual interface to extract hourly weather for all 8 cities from Open-Meteo Archive API, run natural language Pandas transformations, and load datasets into PostgreSQL with duplicate prevention.
5. **Agent Architecture Visualizer**: Step-by-step interactive diagram of the LangGraph multi-agent flow and security policies.

---

## 🌤️ External Data Enrichment (8-City Weather + Mobility)

In real-world ride-hailing operations, external conditions like **precipitation, rain, and temperature** significantly correlate with ride demand, driver availability, cancellation rates, and surge pricing.

```text
                    RIDE DATA (Synthetic)
                              │
                              ▼
                       8 Existing Cities
                              │
  ┌──────────┬──────────┬─────┴────┬──────────┬──────────┐
  ▼          ▼          ▼          ▼          ▼          ▼
Calgary   Edmonton   Halifax    Montreal    Ottawa    Toronto ...
  │          │          │          │          │          │
  └──────────┴──────────┴─────┬────┴──────────┴──────────┘
                              │
                              ▼
                    Open-Meteo Archive API
                              │
                              ▼
                          ETL Agent
                              │
                              ▼
                    weather_data (5,952 Rows)
                              │
                              ▼
                      PostgreSQL Database
                              │
                              ▼
                          SQL Agent
                              │
                              ▼
                 Ride + Weather Analytics
```

### 📍 8 Ride-Hailing Cities & Official Coordinates

The system uses a centralized configuration mapping all 8 ride-hailing cities to their official geographic centers:

```python
CITY_COORDINATES = {
    "Calgary":   {"latitude": 51.0447, "longitude": -114.0719, "province": "AB"},
    "Edmonton":  {"latitude": 53.5461, "longitude": -113.4938, "province": "AB"},
    "Halifax":   {"latitude": 44.6488, "longitude": -63.5752,  "province": "NS"},
    "Montreal":  {"latitude": 45.5017, "longitude": -73.5673,  "province": "QC"},
    "Ottawa":    {"latitude": 45.4215, "longitude": -75.6972,  "province": "ON"},
    "Toronto":   {"latitude": 43.6532, "longitude": -79.3832,  "province": "ON"},
    "Vancouver": {"latitude": 49.2827, "longitude": -123.1207, "province": "BC"},
    "Winnipeg":  {"latitude": 49.8951, "longitude": -97.1384,  "province": "MB"},
}
```

### 🔗 Cross-Table Join Strategy

To combine ride records with external weather:
1. `rides` connects to `users` on `rides.rider_id = users.user_id` to obtain the ride's `city`.
2. `users` connects to `weather_data` on `users.city = weather_data.city`.
3. Timestamp alignment joins hourly observations:
   ```sql
   JOIN public.weather_data w 
     ON u.city = w.city 
    AND DATE_TRUNC('hour', r.requested_at) = w.recorded_at
   ```

### ⚠️ Non-Causal Analytics Policy
All AI answers adhere strictly to observational and correlational terminology (e.g., *"The data shows an association between rainy hours and..."*), avoiding unsupported causal claims (e.g., *"Rain causes surge pricing"*).

---

## 📐 Architecture & Multi-Agent Flow

```text
User Request
    │
    ▼
┌──────────────────┐
│ Router Node      │ ──► Classifies intent (SQL Analytics vs. Weather ETL)
└────────┬─────────┘
         │
    ┌────┴──────────────────────────┐
    ▼                               ▼
┌───────────────────────┐   ┌───────────────────────┐
│ SQL Analyst Agent     │   │ ETL Analyst Agent     │
│                       │   │                       │
│ 1. Question Curation  │   │ • Extract 8 Cities    │
│ 2. Schema Injection   │   │   from Open-Meteo     │
│ 3. SQL Generation     │   │ • Pandas Transforms   │
│ 4. Deterministic Guard│   │ • Duplicate-Safe Load │
│ 5. LLM Security Judge │   │   into PostgreSQL     │
│ 6. Postgres Execution │   └───────────────────────┘
│ 7. Synthesis & Charts │
└───────────────────────┘
```

### 🛡️ SQL Security Architecture (Defense in Depth)

```text
Generated SQL
      │
      ▼
┌──────────────────────────────────────┐
│ Deterministic Syntax & Security Guard│
│ • Must strictly begin with SELECT/WITH│
│ • Rejects backticks, fences, thoughts │
│ • Rejects INSERT, UPDATE, DELETE,    │
│   DROP, ALTER, TRUNCATE, GRANT, etc. │
│ • Rejects chained multi-statements   │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ LLM Security Judge (openai/gpt-oss)  │
│ Independent audit of validated SQL   │
└──────────────────┬───────────────────┘
                   ▼
┌──────────────────────────────────────┐
│ Read-Only PostgreSQL Execution       │
│ Parameterized & JSON serialized      │
└──────────────────────────────────────┘
```

---

## 🚀 Getting Started

### 1. Clone Repository & Setup Environment

```powershell
git clone https://github.com/SoumyaRM2004/OLA_AI_DATA_AGENT.git
cd OLA_AI_DATA_AGENT
```

### 2. Configure `.env` File

Create a `.env` file in the project root:

```env
# PostgreSQL Credentials
host=localhost
port=5432
database=ola_db
user=postgres
password=your_password

# LLM API Keys
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
```

### 3. Install Dependencies & Seed Database

```powershell
# Install dependencies using uv
uv sync

# Extract 8-city weather and seed PostgreSQL
uv run python feed_db.py
```

### 4. Start the Application Server

```powershell
uv run python server.py
```

👉 Open **`http://localhost:8000`** in your browser to access the complete visual dashboard!

---

## 🧪 Example Queries to Try in AI Chat

- *"Compare average rainfall across the 8 cities."*
- *"Show ride cancellation rates during rainy and non-rainy periods."*
- *"Compare average surge multiplier during rainy and non-rainy periods."*
- *"Which city had the highest average rainfall?"*
- *"Compare average fare on rainy versus non-rainy days."*
- *"What are the top 5 highest rated drivers with their average ratings?"*
- *"Show total revenue grouped by payment method."*
- *"Extract weather data for all 8 ride-hailing cities."*

---

## 📂 Project Structure

```text
OLA_AI_DATA_AGENT/
├── agents/
│   ├── data_agent.py          # Master LangGraph Router & execution pipeline
│   ├── sql_analyst.py         # SQL Analyst, prompt context & Security Judge
│   └── etl_analyst.py         # ETL Analyst & tool bindings
├── utils/
│   ├── database.py            # PostgreSQL connection pool & stats aggregator
│   ├── etl_tools.py           # 8-city Open-Meteo extraction & Pandas tools
│   └── llm_pick.py            # Model factory & unified get_message_text helper
├── model/
│   └── schema.py              # Pydantic schemas for structured routing & SQL
├── static/
│   ├── css/style.css          # Glassmorphism dark-theme styling
│   ├── js/app.js              # Vanilla JS frontend & Chart.js renderer
│   └── index.html             # Multi-tab visual dashboard
├── data/
│   ├── users.csv              # Synthetic users across 8 Canadian cities
│   ├── rides.csv              # Synthetic ride records (20,000 trips)
│   ├── vehicles.csv           # Vehicle fleet records
│   ├── payments.csv           # Transaction records
│   ├── ratings.csv            # Driver rating records
│   └── extract/
│       └── weather_data.csv   # Consolidated 8-city hourly weather dataset
├── feed_db.py                 # Database initialization & multi-city seeder
├── server.py                  # FastAPI web server
└── pyproject.toml             # Project dependencies
```

---

## 📄 License
MIT License. Built for educational, analytical, and agentic AI exploration.
