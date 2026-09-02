from pydantic import BaseModel, Field
from typing import Annotated, Literal, List, Dict, Any, Optional
from operator import add


class SQLGenerationSchema(BaseModel):
    can_be_answered: bool = Field(
        default=True,
        description="True if the question can be answered using the provided database schema, False if the requested information or columns do not exist in the schema."
    )
    sql_query: Optional[str] = Field(
        default="",
        description="The valid, single-statement read-only PostgreSQL query (SELECT or WITH). Must be empty or null if can_be_answered is False."
    )
    explanation: Optional[str] = Field(
        default="",
        description="Clear explanation if the question cannot be answered using the schema (e.g. explaining what columns exist and what is missing)."
    )


class IntentSelectionSchema(BaseModel):
    type: Literal["top_n", "bottom_n", "none"] = Field(default="none", description="Selection type: 'top_n', 'bottom_n', or 'none'")
    n: Optional[int] = Field(default=None, description="Number of records to select for top/bottom N (e.g. 10)")
    metric: Optional[str] = Field(default=None, description="The specific metric used to decide which records belong in the top/bottom N (e.g. 'completed_rides')")
    direction: Literal["desc", "asc"] = Field(default="desc", description="Direction of selection ('desc' for top N, 'asc' for bottom N)")


class IntentOrderSchema(BaseModel):
    metric: Optional[str] = Field(default=None, description="The metric used to order/rank the final displayed records (e.g. 'completion_rate')")
    direction: Literal["desc", "asc"] = Field(default="desc", description="Order direction ('desc' or 'asc')")


class IntentFilterSchema(BaseModel):
    metric: str = Field(..., description="Field or metric name being filtered (e.g. 'assigned_rides', 'signup_date')")
    operator: str = Field(..., description="Filter comparison operator (e.g. '>=', '<=', '=', '>', '<', 'ILIKE')")
    value: Any = Field(..., description="Target threshold or comparison value (e.g. 5, '2026', 'completed')")


class StructuredIntentSchema(BaseModel):
    entity: Optional[str] = Field(default="", description="Primary entity being analyzed (e.g. 'driver', 'rider', 'city', 'vehicle')")
    time_range: Optional[str] = Field(default="", description="Requested time period or date range (e.g. '2026', 'January 2025')")
    selection: Optional[IntentSelectionSchema] = Field(default=None, description="Selection ranking determining which records belong in top/bottom N before final display")
    presentation_order: Optional[IntentOrderSchema] = Field(default=None, description="Final presentation order for displaying the selected records")
    filters: List[IntentFilterSchema] = Field(default_factory=list, description="Explicit threshold or dimension filters requested (e.g. >= 5 assigned rides)")
    metrics: List[str] = Field(default_factory=list, description="List of all metrics requested to be calculated (e.g. 'assigned_rides', 'completed_rides', 'completion_rate')")
    comparisons: List[str] = Field(default_factory=list, description="List of comparisons requested (e.g. 'driver cancellation rate vs overall cancellation rate')")


class SemanticValidationSchema(BaseModel):
    is_semantically_valid: bool = Field(
        ...,
        description="True if the SQL faithfully implements the user's analytical intent without logical flaws; False otherwise."
    )
    issues: List[str] = Field(
        default_factory=list,
        description="List of specific analytical or semantic mismatches found between the user intent and generated SQL."
    )
    correction_instruction: Optional[str] = Field(
        default="",
        description="Clear, actionable SQL correction instruction for regenerating faithful SQL."
    )


class AgentSchema(BaseModel):
    messages: Annotated[list, add] = Field(default_factory=list, description="List of messages sent by the agent")
    user_question: str = Field(default="", description="The original question asked by user")
    curated_ques: str = Field(default="", description="Curated user question")
    Prompt_query_context: str = Field(default="", description="A detailed prompt with SQL DB context that will help agent to generate SQL Query for the user question")
    can_be_answered: bool = Field(default=True, description="Whether the question can be answered from schema")
    schema_explanation: str = Field(default="", description="Explanation if question is unanswerable from schema")
    generated_sql_query: str = Field(default="", description="Generated SQL Query for the user question")
    is_safe: Literal["Yes", "No"] = Field(default="No", description="Yes if the SQL query is safe (read-only), No otherwise")
    comments: str = Field(default="", description="Comments regarding whether the SQL query is safe or not")
    sql_query_execution_result: str = Field(default="", description="Text representation of the SQL Query execution result")
    data_columns: List[str] = Field(default_factory=list, description="Column names from SQL execution")
    data_rows: List[List[Any]] = Field(default_factory=list, description="Rows of data from SQL execution")
    data_dicts: List[Dict[str, Any]] = Field(default_factory=list, description="Structured records from SQL execution for charting and table UI")
    final_answer: str = Field(default="", description="Final answer generated by the agent")
    error: str = Field(default="", description="Error message if execution failed")
    session_id: Optional[str] = Field(default=None, description="Optional session identifier for dataset isolation")
    structured_intent: Optional[Dict[str, Any]] = Field(default=None, description="Extracted structured analytical intent")
    semantic_validation_attempts: int = Field(default=0, description="Count of semantic validation / regeneration attempts")
    semantic_issues: List[str] = Field(default_factory=list, description="Issues flagged during semantic intent validation")
    semantic_correction_instruction: str = Field(default="", description="Actionable correction instruction for semantic regeneration")
    is_semantically_valid: bool = Field(default=True, description="True if generated SQL faithfully implements user intent")


class JudgeSchema(BaseModel):
    answer: Literal["Yes", "No"] = Field(
        ...,
        description=(
            "Return 'Yes' if the generated SQL query is safe to execute "
            "and only performs data retrieval. Return 'No' if the query "
            "modifies, deletes, creates, or alters database data or structure."
        )
    )
    comments: str = Field(
        ...,
        description=(
            "Provide a brief explanation for why the SQL query was "
            "considered safe or unsafe."
        )
    )


class EtlAgentSchema(BaseModel):
    messages: Annotated[list, add] = Field(default_factory=list, description="List of messages sent by the ETL agent")
    code_executed: str = Field(default="", description="Pandas code generated and executed")
    execution_result: str = Field(default="", description="Output of the ETL execution")
    output_file: str = Field(default="", description="Path of output file if created")


class RouterSchema(BaseModel):
    answer: Literal["sql", "etl"] = Field(..., description="'sql' if the user question is related to sql database querying, 'etl' if related to extracting/transforming API data or files")
    comments: str = Field(default="", description="Reason for the routing classification")


class DataAgentSchema(BaseModel):
    messages: Annotated[list, add] = Field(default_factory=list, description="List of messages to be processed by the data agent")
    route_response: str = Field(default="", description="Selected route ('sql' or 'etl')")
    sql_state: Optional[Dict[str, Any]] = Field(default=None, description="Detailed state from SQL agent if routed to SQL")
    etl_state: Optional[Dict[str, Any]] = Field(default=None, description="Detailed state from ETL agent if routed to ETL")
    final_answer: str = Field(default="", description="Consolidated final answer")
    session_id: Optional[str] = Field(default=None, description="Optional session identifier for dataset isolation")