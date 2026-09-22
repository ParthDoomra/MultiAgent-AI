from fastapi import APIRouter, Request
from app.api.schemas import (
    FinanceRequest,
    FinanceResponse,
    MarketRequest,
    MarketResponse,
    SalesRequest,
    SalesResponse,
    ReportRequest,
    ReportResponse,
    OrchestrateRequest,
    OrchestrateResponse,
)
from app.services.finance_service import calculate_finance
from app.services.market_service import analyze_market
from app.services.sales_service import analyze_sales
from app.services.report_service import generate_business_report
from app.services.orchestrator_service import orchestrate_request

router = APIRouter()


@router.post("/agents/finance", response_model=FinanceResponse, summary="Finance Agent Endpoint")
def finance_endpoint(payload: FinanceRequest):
    """
    Finance Agent: Calls Microsoft Foundry Finance Agent via thread execution.
    Computes revenue, total cost, gross profit, and margin percentage.
    """
    return calculate_finance(payload)


@router.post("/agents/market", response_model=MarketResponse, summary="Market Research Agent Endpoint")
def market_endpoint(payload: MarketRequest):
    """
    Market Agent: Uses web search tool to retrieve real competitor data and market analysis.
    """
    return analyze_market(payload)


@router.post("/agents/sales", response_model=SalesResponse, summary="Sales Negotiation Agent Endpoint")
def sales_endpoint(payload: SalesRequest):
    """
    Sales Agent: Determines negotiation range, minimum acceptable price, opening offer,
    and strategic talking points given finance margin data and market competitor benchmarks.
    """
    return analyze_sales(payload)


@router.post("/agents/report", response_model=ReportResponse, summary="Report Agent Endpoint")
def report_endpoint(payload: ReportRequest):
    """
    Report Agent: Synthesizes combined outputs of Finance, Market, and optional Sales agents into a final recommendation.
    """
    return generate_business_report(payload)


@router.post("/orchestrate", response_model=OrchestrateResponse, summary="Orchestrator Agent Endpoint")
async def orchestrate_endpoint(payload: OrchestrateRequest, request: Request):
    """
    Orchestrator Agent: Parses user query, invokes needed agents via REST, and synthesizes final report.
    """
    # Detect running host and port dynamically
    base_url = str(request.base_url).rstrip("/")
    return await orchestrate_request(payload, base_url=base_url)
