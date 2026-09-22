import logging
from typing import Any, Dict
from app.api.schemas import ReportRequest, ReportResponse
from app.services.foundry_client import run_report_agent_thread

logger = logging.getLogger(__name__)


def generate_business_report(data: ReportRequest) -> ReportResponse:
    """
    Report Agent: Invokes Microsoft Foundry report-agent via dedicated thread execution.
    Synthesizes combined outputs of Finance and Market agents into a structured business
    decision and recommendation.
    
    Surfaces any error directly without silent fallback so issues can be diagnosed.
    """
    # Extract finance and market dictionaries
    if data.finance and hasattr(data.finance, "model_dump"):
        finance_dict = data.finance.model_dump()
    elif isinstance(data.finance, dict):
        finance_dict = data.finance
    else:
        finance_dict = {}

    if data.market and hasattr(data.market, "model_dump"):
        market_dict = data.market.model_dump()
    elif isinstance(data.market, dict):
        market_dict = data.market
    else:
        market_dict = {}

    sales_dict = None
    if data.sales:
        if hasattr(data.sales, "model_dump"):
            sales_dict = data.sales.model_dump()
        elif isinstance(data.sales, dict):
            sales_dict = data.sales

    logger.info("Invoking Foundry Report Agent with finance, market, and sales perspectives")

    # Call the Foundry agent directly; errors will propagate clearly
    result = run_report_agent_thread(
        finance_data=finance_dict,
        market_data=market_dict,
        sales_data=sales_dict
    )

    # Normalize recommendation: strictly "LAUNCH" or "DO NOT LAUNCH"
    recommendation_raw = str(result.get("recommendation", "LAUNCH")).upper().strip()
    if "DO NOT LAUNCH" in recommendation_raw or "NO" in recommendation_raw or "RETHINK" in recommendation_raw:
        recommendation = "DO NOT LAUNCH"
    else:
        recommendation = "LAUNCH"

    # Normalize actions as list of strings
    raw_actions = result.get("actions", [])
    if isinstance(raw_actions, list):
        actions = [str(a) for a in raw_actions]
    elif raw_actions:
        actions = [str(raw_actions)]
    else:
        actions = []

    # Normalize key_factors as list of strings
    raw_factors = result.get("key_factors", [])
    if isinstance(raw_factors, list):
        key_factors = [str(k) for k in raw_factors]
    elif raw_factors:
        key_factors = [str(raw_factors)]
    else:
        key_factors = []

    # Resolve numerical fields with safe fallbacks to finance inputs if missing
    recommended_price = float(result.get("recommended_price", finance_dict.get("price", 0.0) or 0.0))
    estimated_margin = float(result.get("estimated_margin", finance_dict.get("margin_percent", 0.0) or 0.0))
    market_potential = str(result.get("market_potential", "Moderate"))
    main_risk = str(result.get("main_risk", ""))
    summary = result.get("summary")

    return ReportResponse(
        market_potential=market_potential,
        recommended_price=recommended_price,
        estimated_margin=estimated_margin,
        main_risk=main_risk,
        recommendation=recommendation,
        summary=summary,
        actions=actions,
        key_factors=key_factors
    )
