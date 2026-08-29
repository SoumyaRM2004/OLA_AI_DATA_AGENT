# 🚗 OLA AI Data Agent

An AI-powered, multi-agent analytics and ETL platform for OLA ride-hailing data — built with **LangGraph**, **FastAPI**, **PostgreSQL**, and a modern **HTML5/CSS3/JS** interactive visual dashboard.

Ask questions in natural English, and the agent automatically routes your request to specialized sub-agents:
- **SQL Analyst** — Natural language to PostgreSQL with an automated **"LLM as Judge"** security audit, auto-generated interactive charts (Bar, Line, Doughnut), and exportable data tables.
- **ETL Analyst** — Extract from any REST API, automatically generate & execute Pandas transformations, and inspect datasets.

![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_AI-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Modern_Web-teal?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-blue?logo=postgresql)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## 🌟 Interactive Web Dashboard

The application comes with a dark-themed glassmorphism web interface featuring:

1. **AI Chat Studio**: Interactive conversation, suggested query chips, agent execution timeline (Router &rarr; Question Curation &rarr; SQL Generation &rarr; Security Judge &rarr; Execution), with **auto-generated Chart.js charts** and searchable tables.
2. **Analytics KPI Dashboard**: Live KPI cards (total rides, completed rides, total revenue, average driver ratings) with breakdown graphs.
3. **Database Explorer**: Live database schema inspector, table data viewer, search/filtering, and row counts for all 5 OLA tables.
4. **ETL Studio**: Visual interface to extract from any API endpoint (JSON/CSV/Parquet) and run natural language transformations.
5. **Agent Architecture Visualizer**: Step-by-step breakdown of the LangGraph multi-agent flow and security policies.

---

## 📐 Architecture

```
                    ┌──────────────────┐
                    │   User Question  │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │   Data Agent     │
                    │   (Router)       │
                    │   LLM classifies │
                    │   → "sql" / "etl"│
                    └───┬──────────┬───┘
                        │          │
              ┌─────────▼──┐  ┌───▼──────────┐
              │ SQL Analyst │  │ ETL Analyst  │
              │   Agent     │  │   Agent      │
              └─────────────┘  └──────────────┘
```

### 🔍 SQL Analyst Pipeline

```
User Question
    │
    ▼
┌─────────────────┐
│ 1. Curate       │ ──→ Rewrites question for clarity
│    Question     │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 2. Build Prompt │ ──→ Fetches DB schema + sample data
│    + Context    │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 3. Generate SQL │ ──→ LLM writes PostgreSQL query
└────────┬────────┘
         ▼
┌─────────────────┐
│ 4. Security     │ ──→ "LLM as Judge" checks for unsafe
│    Judge        │     operations (INSERT/DELETE/DROP...)
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
│ 5. Synthesize   │ ──→ Natural language answer + Tabular data
│    & Visualize  │     + Dynamic Chart.js visualizations
└─────────────────┘
```

### 🔄 ETL Analyst Pipeline

```
User Question
    │
    ▼
┌─────────────────┐
│ LLM Node        │ ──→ Decides which tool to use
└────────┬────────┘
         ▼
    ┌────┴────────────┐
    │                 │
┌───▼──────────┐ ┌───▼──────────────┐
│ Extract &    │ │ Transform &      │
│ Load Tool    │ │ Load Tool        │
│              │ │                  │
│ API → CSV/   │ │ LLM generates    │
│ JSON/Parquet │ │ Pandas code →    │
│              │ │ executes it      │
└──────────────┘ └──────────────────┘
```

---

## 🗄️ Database Schema (OLA Ride-Hailing)

The project uses a realistic ride-hailing dataset with 5 interconnected tables:

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
         ┌────▼─────┐    ┌─────▼────┐
         │ PAYMENTS │    │ RATINGS  │
         │          │    │          │
         │payment_id│    │rating_id │
         │ ride_id  │    │ ride_id  │
         │ amount   │    │ rating   │
         │ method   │    │ comment  │
         │ status   │    │ rated_at │
         └──────────┘    └──────────┘
```

---

## 🧠 Multi-Tier LLM Strategy

The project intelligently uses different LLM models based on task complexity to balance **cost**, **speed**, and **accuracy**:

| Tier | Model | Used For |
|------|-------|----------|
| 🟢 **Low** | `openai/gpt-oss-20b` (Groq) | Question curation, answer formatting |
| 🟡 **Medium** | `qwen/qwen3.6-27b` (Groq) | SQL generation |
| 🔴 **High** | `openai/gpt-oss-120b` (Groq) | SQL security validation judge |
| 💎 **Gemini** | `gemini-3.5-flash` (Google) | Router classification & ETL tool binding |

---

## 📂 Project Structure

```
OLA_AI_DataAgent/
│
├── agents/                    # LangGraph agent definitions
│   ├── data_agent.py          # Main router agent & chart detector
│   ├── sql_analyst.py         # SQL generation, security judge & execution
│   └── etl_analyst.py         # Extract/Transform/Load operations
│
├── model/                     # Pydantic schemas
│   └── schema.py              # AgentSchema, RouterSchema, JudgeSchema
│
├── utils/                     # Utility modules
│   ├── database.py            # PostgreSQL connection & structured execution
│   ├── etl_tools.py           # ETL operations (extract, transform, load, preview)
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
│   ├── *.csv                  # Raw OLA dataset (users, rides, payments, ratings, vehicles)
│   ├── extract/               # Extracted API data output
│   └── transform/             # Transformed data output
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

Load the OLA dataset into PostgreSQL:

```bash
uv run python feed_db.py
```

This creates 5 tables (`users`, `vehicles`, `rides`, `payments`, `ratings`) and loads ~15,000+ records.

### 5. Launch the Web Application

Start the FastAPI web server:

```bash
uv run python server.py
```

Or via `main.py`:

```bash
uv run python main.py --server
```

Now open your browser and navigate to **`http://localhost:8000`**!

---

## 💡 Example Queries

### SQL Queries (Natural Language → SQL → Chart & Table)

```
"What are the top 5 highest rated drivers with their average ratings?"
"Show total revenue grouped by payment method"
"What is the distribution of ride statuses?"
"What is the average fare and distance for completed rides?"
"Show top 5 cities by total number of completed rides"
```

### ETL Operations

```
"Extract data from https://pokeapi.co/api/v2/pokemon and save to data/extract as csv"
"Transform data/extract/extracted_data.csv and filter only names starting with 'b', save to data/transform as csv"
```

---

## 🔒 Security Features

- **SQL Security Judge** — Every generated SQL query is validated by an LLM judge before execution
- **Read-Only Enforcement** — INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE operations are blocked
- **Structured Validation** — Pydantic schemas enforce type safety on all LLM responses
- **Environment Variables** — All secrets stored in `.env` (never hardcoded in repository)

---

## 🛠️ Tech Stack

| Technology | Purpose |
|-----------|---------|
| [LangGraph](https://langchain-ai.github.io/langgraph/) | Multi-agent orchestration with state graphs |
| [LangChain](https://www.langchain.com/) | LLM integration, tool calling, message handling |
| [FastAPI](https://fastapi.tiangolo.com/) | High-performance Python web backend & REST API |
| [Chart.js](https://www.chartjs.org/) | Auto-generated responsive client-side charts |
| [Lucide Icons](https://lucide.dev/) | Modern UI icons |
| [Groq](https://groq.com/) | Ultra-fast LLM inference (free tier) |
| [Google Gemini](https://ai.google.dev/) | Tool calling & router classification |
| [PostgreSQL](https://www.postgresql.org/) | Relational database for OLA dataset |
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
