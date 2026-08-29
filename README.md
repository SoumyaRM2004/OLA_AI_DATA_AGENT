# 🚗 OLA AI Data Agent

An AI-powered, multi-agent analytics and ETL platform for **OLA-inspired ride-hailing data** — built with **LangGraph**, **FastAPI**, **PostgreSQL**, and a modern **HTML5/CSS3/JavaScript** interactive visual dashboard.

Ask questions in plain English, and the agent automatically routes your request to specialized sub-agents:
- **SQL Analyst** — Natural language to PostgreSQL queries with an automated **"LLM as Judge"** security audit, auto-generated interactive charts (Bar, Line, Doughnut), and exportable data tables.
- **ETL Analyst** — Extracts external **Open-Meteo weather data** and other open APIs, transforms datasets using Pandas, and loads them into PostgreSQL for cross-domain mobility analytics.

> ℹ️ **Dataset Note**: The ride-hailing data used in this project is an **OLA-inspired synthetic dataset** modeled for realistic mobility analytics (rides, drivers, vehicles, payments, ratings). Weather integration demonstrates how an AI data platform enriches mobility operations with external contextual data.

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
2. **Analytics KPI Dashboard**: Live KPI cards (total rides, completed rides, total revenue in ₹, average driver ratings) with breakdown graphs.
3. **Database Explorer**: Live schema inspector, table data viewer, search/filtering, and row counts across all 6 tables (`users`, `vehicles`, `rides`, `payments`, `ratings`, `weather_data`).
4. **Weather ETL Studio**: Visual interface to extract hourly weather from Open-Meteo or any external REST API, run natural language Pandas transformations, and load datasets into PostgreSQL with one click.
5. **Agent Architecture Visualizer**: Step-by-step interactive diagram of the LangGraph multi-agent flow and security policies.

---

## 🌤️ External Data Enrichment (Weather + Mobility)

In real-world ride-hailing operations, external conditions like **precipitation, rain, and temperature** significantly correlate with ride demand, driver availability, cancellation rates, and surge pricing.

```
OLA-inspired ride data
        +
External weather data (Open-Meteo)
        ↓
ETL pipeline
        ↓
PostgreSQL (weather_data)
        ↓
AI-powered SQL Analytics
        ↓
Insights & Visualizations
```

### Supported Correlation Analyses:
- **Rain vs. Cancellations**: Analyzing cancellation percentages during rainy vs. clear weather intervals.
- **Weather vs. Surge Multiplier**: Comparing average surge multipliers and fares across rainy and dry periods.
- **Daily Weather Summaries**: Aggregating precipitation and temperature trends by date.

*Note: Analyses represent statistical correlations observed in the dataset rather than direct claims of causation.*

---

## 📐 Architecture

```
                         USER
                           │
                           ▼
                     DATA AGENT (Router)
                     /         \
                    /           \
                   ▼             ▼
             SQL ANALYST     ETL ANALYST
                  │                │
                  ▼                ▼
             PostgreSQL       External APIs
             (OLA Data)      (Open-Meteo)
                  │                │
                  └───────┬────────┘
                          ▼
                   Structured Data
                          │
                          ▼
                    AI Analytics
                          │
                          ▼
                Tables / Charts / Insights
```

### 🔍 SQL Analyst Pipeline

```
User Question
    │
    ▼
┌─────────────────┐
│ 1. Curate       │ ──→ Rewrites question for clarity & PostgreSQL context
│    Question     │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. Build Prompt │ ──→ Fetches DB schema (rides, users, weather_data, etc.)
│    + Context    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. Generate SQL │ ──→ LLM writes PostgreSQL query with proper JOINs
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. Security     │ ──→ "LLM as Judge" checks for unsafe operations
│    Judge        │     (blocks INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE)
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
  ✅ Safe   ❌ Unsafe
    │         │
    ▼         ▼
┌────────┐ ┌────────────┐
│Execute │ │  Blocked!  │
│  SQL   │ │  + Reason  │
└───┬────┘ └────────────┘
    ▼
┌─────────────────┐
│ 5. Synthesize   │ ──→ Natural language answer + Tabular records
│    & Visualize  │     + Dynamic Chart.js visualizations
└─────────────────┘
```

### 🔄 ETL Analyst Pipeline

```
User Question / API URL
    │
    ▼
┌─────────────────┐
│ LLM Node        │ ──→ Selects appropriate tool
└────────┬────────┘
         ▼
    ┌────┴─────────────────────────┐
    │                              │
┌───▼──────────┐ ┌───▼──────────────┐ ┌───▼──────────────┐
│ Extract &    │ │ Transform &      │ │ Load to          │
│ Load Tool    │ │ Load Tool        │ │ Database Tool    │
│              │ │                  │ │                  │
│ Open-Meteo   │ │ LLM generates    │ │ Inserts dataset  │
│ API → CSV/   │ │ Pandas code →    │ │ into PostgreSQL  │
│ JSON/Parquet │ │ executes safely  │ │ (weather_data)   │
└──────────────┘ └──────────────────┘ └──────────────────┘
```

---

## 🗄️ Database Schema

The database contains 6 interconnected tables:

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  USERS   │◄────│  RIDES   │────►│ VEHICLES │
│          │     │          │     │          │
│ user_id  │     │ ride_id  │     │vehicle_id│
│ name     │     │ rider_id │     │ driver_id│
│ email    │     │ driver_id│     │ make     │
│ city     │     │ fare     │     │ model    │
│ user_type│     │ distance │     │ color    │
│ is_active│     │ status   │     │ plate    │
└──────────┘     └─────┬────┘     └──────────┘
                       │
              ┌────────┴────────┐
              │                 │
         ┌────▼─────┐    ┌─────▼────┐    ┌─────────────────┐
         │ PAYMENTS │    │ RATINGS  │    │  WEATHER_DATA   │
         │          │    │          │    │                 │
         │payment_id│    │rating_id │    │ weather_id (PK) │
         │ ride_id  │    │ ride_id  │    │ recorded_at     │
         │ amount   │    │ rating   │    │ city / lat / lon│
         │ method   │    │ comment  │    │ temperature_c   │
         │ status   │    │ rated_at │    │ precipitation_mm│
         └──────────┘    └──────────┘    │ rain_mm / rainy │
                                         └─────────────────┘
```

---

## 🧠 Multi-Tier LLM Strategy

The project intelligently uses different LLM models based on task complexity to balance **cost**, **speed**, and **accuracy**:

| Tier | Model | Used For |
|------|-------|----------|
| 🟢 **Low** | `openai/gpt-oss-20b` (Groq) | Question curation & answer formatting |
| 🟡 **Medium** | `qwen/qwen3.6-27b` (Groq) | PostgreSQL SQL generation |
| 🔴 **High** | `openai/gpt-oss-120b` (Groq) | SQL security validation judge |
| 💎 **Gemini** | `gemini-3.5-flash` (Google) | Router classification & ETL tool calling |

---

## 📂 Project Structure

```
OLA_AI_DataAgent/
│
├── agents/                    # LangGraph agent definitions
│   ├── data_agent.py          # Main router agent & chart detector
│   ├── sql_analyst.py         # SQL generation, security judge & execution
│   └── etl_analyst.py         # Open-Meteo extraction & Pandas transform
│
├── model/                     # Pydantic schemas
│   └── schema.py              # AgentSchema, RouterSchema, JudgeSchema
│
├── utils/                     # Utility modules
│   ├── database.py            # PostgreSQL connection & structured execution
│   ├── etl_tools.py           # ETL operations (extract, transform, preview, load)
│   └── llm_pick.py            # Multi-tier LLM selector
│
├── static/                    # Modern Web Frontend
│   ├── index.html             # Single-page dashboard application
│   ├── css/
│   │   └── style.css          # Glassmorphism dark theme styling
│   └── js/
│       └── app.js             # Chat streaming, Chart.js, and explorer logic
│
├── data/                      # Data directory
│   ├── *.csv                  # Synthetic OLA dataset (users, rides, payments, ratings, vehicles)
│   ├── extract/               # Extracted weather and API data output
│   └── transform/             # Transformed dataset output
│
├── Pictures/                  # Architecture diagrams
│
├── server.py                  # FastAPI server & REST API
├── main.py                    # CLI entry point & runner
├── feed_db.py                 # Database setup & CSV loader
├── pyproject.toml             # Project config & dependencies
├── .env.example               # Environment variable template
├── LICENSE                    # MIT License
└── README.md                  # You are here!
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.12+**
- **PostgreSQL** (running locally or remote)
- **UV** package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- **Groq API Key** ([get free key](https://console.groq.com/keys))
- **Google Gemini API Key** ([get free key](https://aistudio.google.com/apikey))

### 1. Clone the Repository

```bash
git clone https://github.com/SoumyaRM2004/OLA_AI_DATA_AGENT.git
cd OLA_AI_DATA_AGENT
```

### 2. Install Dependencies

```bash
uv sync
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your actual API keys and database credentials:

```env
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here

host=localhost
port=5432
database=postgres
user=postgres
password=your_db_password
```

### 4. Setup the Database

Create all tables (`users`, `vehicles`, `rides`, `payments`, `ratings`, `weather_data`) and seed the dataset:

```bash
uv run python feed_db.py
```

### 5. Launch the Web Application

Start the FastAPI web server:

```bash
uv run python server.py
```

Or via `main.py`:

```bash
uv run python main.py --server
```

Now open your browser and navigate to:
👉 **`http://localhost:8000`**

---

## 💡 Example Queries

### Weather & Mobility Correlation Queries

```
"Does rainfall correlate with ride cancellations?"
"Compare average surge multiplier during rainy and non-rainy periods"
"Show average rainfall and temperature by date from weather data"
"What is the total ride count and cancellation rate during rainy hours?"
```

### General OLA Ride-Hailing Analytics

```
"What are the top 5 highest rated drivers with their average ratings?"
"Show total revenue grouped by payment method"
"What is the distribution of ride statuses?"
"What is the average fare and distance for completed rides?"
"Show top 5 cities by total number of completed rides"
```

### ETL Operations

```
"Extract weather data from https://api.open-meteo.com/v1/forecast?latitude=43.65&longitude=-79.38&hourly=temperature_2m,precipitation,rain,weather_code and save to data/extract as csv"
"Transform data/extract/weather_data.csv and filter hours where rain_mm > 0, save to data/transform as csv"
```

---

## 🔒 Security Features

- **SQL Security Judge** — Every generated SQL query is audited by an LLM judge before database execution.
- **Read-Only Enforcement** — Mutating commands (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `REVOKE`) are blocked.
- **Parameterized Queries** — SQL execution uses parameterization and identifier escaping.
- **Structured Validation** — Pydantic schemas enforce type safety on all agent outputs.
- **Environment Variables** — All secrets are kept in `.env` (gitignored; never committed).

---

## 🛠️ Tech Stack

| Technology | Purpose |
|-----------|---------|
| [LangGraph](https://langchain-ai.github.io/langgraph/) | Multi-agent orchestration with state graphs |
| [LangChain](https://www.langchain.com/) | LLM integration, tool calling, message handling |
| [FastAPI](https://fastapi.tiangolo.com/) | Python web backend & REST API |
| [Chart.js](https://www.chartjs.org/) | Auto-generated responsive client-side charts |
| [Open-Meteo](https://open-meteo.com/) | Free, open-source weather forecast & archive API |
| [Lucide Icons](https://lucide.dev/) | Modern UI iconography |
| [Groq](https://groq.com/) | Fast LLM inference (Llama/Qwen/GPT-OSS) |
| [Google Gemini](https://ai.google.dev/) | Tool calling & router classification |
| [PostgreSQL](https://www.postgresql.org/) | Relational database for ride-hailing & weather data |
| [Pydantic](https://docs.pydantic.dev/) | Schema validation and structured outputs |
| [Pandas](https://pandas.pydata.org/) | Data transformation in ETL pipeline |
| [UV](https://docs.astral.sh/uv/) | Fast Python package manager |

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Soumya Ranjan Mohapatra**

- GitHub: [@SoumyaRM2004](https://github.com/SoumyaRM2004)
