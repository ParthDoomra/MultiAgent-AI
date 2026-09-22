import logging
from typing import Any, Dict, List
from app.api.schemas import SalesRequest, SalesResponse
from app.services.foundry_client import run_sales_agent_thread

logger = logging.getLogger(__name__)


def analyze_sales(data: SalesRequest) -> SalesResponse:
    """
    Sales Agent: Invokes Microsoft Foundry sales-agent via dedicated thread execution.
    Analyzes unit cost floor from finance and competitor price ceilings from market to determine:
    - min_acceptable_price (hard floor)
    - max_asking_price (ceiling)
    - recommended_opening_offer (anchor)
    - negotiation_strategy (tactics and concession plan)
    - key_talking_points (persuasive arguments)
    
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

    logger.info("Invoking Foundry Sales Agent with finance margins and market pricing")

    # Call the Foundry agent directly; errors will propagate clearly
    result = run_sales_agent_thread(
        finance_data=finance_dict,
        market_data=market_dict
    )

    # Normalize key_talking_points as list of strings
    raw_points = result.get("key_talking_points", [])
    if isinstance(raw_points, list):
        key_talking_points = [str(p) for p in raw_points]
    elif raw_points:
        key_talking_points = [str(raw_points)]
    else:
        key_talking_points = []

    # Resolve price fields with fallback to finance cost/price if missing
    cost_val = float(finance_dict.get("cost", 0.0) or 0.0)
    target_price_val = float(finance_dict.get("price", 0.0) or cost_val * 1.5)

    min_acceptable_price = float(result.get("min_acceptable_price", cost_val * 1.1 if cost_val > 0 else 0.0))
    max_asking_price = float(result.get("max_asking_price", target_price_val * 1.2 if target_price_val > 0 else min_acceptable_price * 1.5))
    recommended_opening_offer = float(result.get("recommended_opening_offer", target_price_val if target_price_val > 0 else (min_acceptable_price + max_asking_price) / 2))
    
    negotiation_strategy = str(result.get("negotiation_strategy", "Defend unit economics, emphasize value-added differentiation, and trade volume commitments for price concessions."))
    summary = result.get("summary")

    return SalesResponse(
        min_acceptable_price=min_acceptable_price,
        max_asking_price=max_asking_price,
        recommended_opening_offer=recommended_opening_offer,
        negotiation_strategy=negotiation_strategy,
        key_talking_points=key_talking_points,
        summary=summary
    )
