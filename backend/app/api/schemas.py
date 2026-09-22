from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator


# --- Finance Agent Schemas ---

class FinanceRequest(BaseModel):
    cost: float = Field(..., description="Manufacturing or procurement cost per unit")
    price: float = Field(..., description="Target selling price per unit")
    expected_units: int = Field(..., description="Projected sales volume in units", gt=0)


class FinanceResponse(BaseModel):
    revenue: float = Field(..., description="Total projected revenue")
    cost_total: float = Field(..., description="Total projected costs")
    gross_profit: float = Field(..., description="Total gross profit")
    margin_percent: float = Field(..., description="Gross margin percentage")
    
    # Optional supplementary fields for convenience
    cost: Optional[float] = None
    price: Optional[float] = None
    expected_units: Optional[int] = None
    profit_per_unit: Optional[float] = None
    summary: Optional[str] = None


# --- Market Agent Schemas ---

class MarketRequest(BaseModel):
    product: str = Field(..., description="Name or category of the product to research")
    target_market: str = Field("India", description="Geographic or demographic target market")


class MarketResponse(BaseModel):
    market_size: str = Field(..., description="Estimated market size and volume/growth dynamics")
    competitors: List[str] = Field(..., description="List of key competitors with pricing and positioning")
    opportunities: List[str] = Field(..., description="Key growth opportunities in the market")
    risks: List[str] = Field(..., description="Major risks and hurdles to enter this market")
    
    # Optional supplementary fields
    product: Optional[str] = None
    target_market: Optional[str] = None
    summary: Optional[str] = None


# --- Sales Agent Schemas ---

class SalesRequest(BaseModel):
    finance: Optional[FinanceResponse] = None
    market: Optional[MarketResponse] = None
    agents: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def extract_nested_agents(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "agents" in data and isinstance(data["agents"], dict):
                agents_dict = data["agents"]
                if "finance" not in data and "finance" in agents_dict:
                    data["finance"] = agents_dict["finance"]
                if "market" not in data and "market" in agents_dict:
                    data["market"] = agents_dict["market"]
        return data


class SalesResponse(BaseModel):
    min_acceptable_price: float = Field(..., description="Lowest acceptable price without losing money (cost + minimum margin)")
    max_asking_price: float = Field(..., description="Highest viable asking price based on competitive ceiling")
    recommended_opening_offer: float = Field(..., description="Recommended opening price anchor for negotiation")
    negotiation_strategy: str = Field(..., description="Strategic approach and concession plan")
    key_talking_points: List[str] = Field(..., description="Persuasive value propositions and trade-off arguments")
    summary: Optional[str] = None


# --- Report Agent Schemas ---

class ReportRequest(BaseModel):
    finance: Optional[FinanceResponse] = None
    market: Optional[MarketResponse] = None
    sales: Optional[SalesResponse] = None
    agents: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def extract_nested_agents(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If payload was sent as { "agents": { "finance": ..., "market": ..., "sales": ... } }
            if "agents" in data and isinstance(data["agents"], dict):
                agents_dict = data["agents"]
                if "finance" not in data and "finance" in agents_dict:
                    data["finance"] = agents_dict["finance"]
                if "market" not in data and "market" in agents_dict:
                    data["market"] = agents_dict["market"]
                if "sales" not in data and "sales" in agents_dict:
                    data["sales"] = agents_dict["sales"]
        return data



class ReportResponse(BaseModel):
    market_potential: str = Field(..., description="Market potential assessment (e.g., High, Moderate, Low)")
    recommended_price: float = Field(..., description="Recommended selling price")
    estimated_margin: float = Field(..., description="Estimated gross profit margin percentage as float")
    main_risk: str = Field(..., description="Primary risk identified for this venture")
    recommendation: Literal["LAUNCH", "DO NOT LAUNCH"] = Field(..., description="Verdict: LAUNCH or DO NOT LAUNCH")
    
    # Optional metadata fields helpful for display
    summary: Optional[str] = None
    actions: Optional[List[str]] = None
    key_factors: Optional[List[str]] = None


# --- Orchestrator Schemas ---

class ConversationTurn(BaseModel):
    """A single turn in the conversation history."""
    role: Literal["user", "assistant"] = Field(..., description="Who sent this message")
    content: str = Field(..., description="The message content")


class OrchestrateRequest(BaseModel):
    """
    Multi-turn orchestration request.
    Backwards-compatible: session_id and history are optional,
    so the old {"query": "..."} shape still works.
    """
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID for multi-turn conversations. Auto-generated if not provided."
    )
    history: List[ConversationTurn] = Field(
        default=[],
        description="Full conversation history so far (all prior turns). "
                    "The orchestrator uses this to carry context across follow-up questions."
    )
    query: str = Field(..., description="The new user message/question")


class OrchestrateResponse(BaseModel):
    """
    Multi-turn orchestration response.
    type='clarification': the system needs more info — read `message`.
    type='result': full analysis is ready — read `agents` and `report`.
    """
    type: Literal["clarification", "result"] = Field(
        ..., description="'clarification' if more info is needed, 'result' if the full report is ready"
    )
    session_id: str = Field(..., description="Session ID — echo back in the next request's history")
    message: Optional[str] = Field(
        default=None,
        description="The clarifying question to show the user (only present when type='clarification')"
    )

    # Present only when type='result'
    agents: Optional[Dict[str, Any]] = Field(
        default=None, description="Outputs from invoked agents: finance, market"
    )
    report: Optional[ReportResponse] = Field(
        default=None, description="Final synthesized business report"
    )

    # Top-level aliases to guarantee interoperability with external frontends
    finance: Optional[Dict[str, Any]] = None
    market: Optional[Dict[str, Any]] = None
    sales: Optional[Dict[str, Any]] = None

