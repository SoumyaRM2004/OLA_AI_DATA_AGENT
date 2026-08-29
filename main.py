import sys
from agents.data_agent import execute_agent_query

def main():
    print("=" * 60)
    print("🚗 OLA AI Data Agent (Multi-Agent System with SQL & ETL)")
    print("=" * 60)

    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        import uvicorn
        print("\n🌐 Launching Interactive Web Dashboard on http://localhost:8000 ...\n")
        uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
        return

    # Default CLI interactive mode
    print("\nTip: Run with `python main.py --server` to launch the Web UI!")
    print("Type your query below or type 'exit' to quit.\n")

    # Sample query if no stdin
    default_prompt = "What are the top 5 highest rated drivers with their average ratings?"
    print(f"Executing sample query: '{default_prompt}'\n")
    
    result = execute_agent_query(default_prompt)
    
    print("\n" + "=" * 40 + " RESULT " + "=" * 40)
    print(f"Route: {result.get('route', '').upper()} Analyst")
    if result.get("sql_query"):
        print(f"Generated SQL:\n{result['sql_query']}")
        print(f"Security Check: {result.get('is_safe')} ({result.get('judge_comments')})")
    print(f"\nFinal Answer:\n{result.get('answer')}")
    print("=" * 88)

if __name__ == "__main__":
    main()
