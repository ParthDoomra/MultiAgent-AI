import logging
from app.api.schemas import MarketRequest, MarketResponse
from app.services.foundry_client import run_market_agent_thread

logger = logging.getLogger(__name__)


def analyze_market(data: MarketRequest) -> MarketResponse:
    """
    Market Agent: Invokes Microsoft Foundry market-agent via dedicated thread execution.
    Researches competitors, market size, opportunities, and risks for the given product and target_market.
    
    Surfaces any error directly without silent fallback so issues can be inspected and debugged.
    """
    logger.info(f"Invoking Foundry Market Agent for product='{data.product}', target_market='{data.target_market}'")

    # Call the Foundry agent directly; errors will propagate clearly
    result = run_market_agent_thread(
        product=data.product,
        target_market=data.target_market
    )

    # Format competitors as list of strings
    raw_competitors = result.get("competitors", [])
    if isinstance(raw_competitors, list):
        competitors = [str(c) for c in raw_competitors]
    elif raw_competitors:
        competitors = [str(raw_competitors)]
    else:
        competitors = []

    # Format opportunities as list of strings
    raw_opps = result.get("opportunities", [])
    if isinstance(raw_opps, list):
        opportunities = [str(o) for o in raw_opps]
    elif raw_opps:
        opportunities = [str(raw_opps)]
    else:
        opportunities = []

    # Format risks as list of strings
    raw_risks = result.get("risks", [])
    if isinstance(raw_risks, list):
        risks = [str(r) for r in raw_risks]
    elif raw_risks:
        risks = [str(raw_risks)]
    else:
        risks = []

    market_size = str(result.get("market_size", ""))
    summary = result.get("summary")

    return MarketResponse(
        market_size=market_size,
        competitors=competitors,
        opportunities=opportunities,
        risks=risks,
        product=data.product,
        target_market=data.target_market,
        summary=summary
    )
