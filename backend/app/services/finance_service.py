import logging
from app.api.schemas import FinanceRequest, FinanceResponse
from app.services.foundry_client import run_finance_agent_thread

logger = logging.getLogger(__name__)


def _calculate_finance_local(cost: float, price: float, units: int) -> FinanceResponse:
    """Local deterministic fallback calculation."""
    revenue = round(price * units, 2)
    cost_total = round(cost * units, 2)
    gross_profit = round(revenue - cost_total, 2)
    margin_percent = round((gross_profit / revenue) * 100, 2) if revenue > 0 else 0.0
    profit_per_unit = round(price - cost, 2)

    return FinanceResponse(
        revenue=revenue,
        cost_total=cost_total,
        gross_profit=gross_profit,
        margin_percent=margin_percent,
        cost=cost,
        price=price,
        expected_units=units,
        profit_per_unit=profit_per_unit,
        summary=f"Unit economics: ₹{price:,.2f} selling price against ₹{cost:,.2f} cost yields ₹{profit_per_unit:,.2f} profit/unit ({margin_percent:.2f}% gross margin)."
    )


def calculate_finance(data: FinanceRequest) -> FinanceResponse:
    """
    Finance Agent: Invokes Microsoft Foundry agent via thread execution.
    Computes revenue, total cost, gross profit, margin percentage, and unit economics.
    """
    cost = float(data.cost)
    price = float(data.price)
    units = int(data.expected_units)

    try:
        logger.info(f"Invoking Foundry Finance Agent for cost={cost}, price={price}, units={units}")
        foundry_result = run_finance_agent_thread(cost=cost, price=price, expected_units=units)
        
        # Extract and format fields
        revenue = float(foundry_result.get("revenue", round(price * units, 2)))
        cost_total = float(foundry_result.get("cost_total", round(cost * units, 2)))
        gross_profit = float(foundry_result.get("gross_profit", round(revenue - cost_total, 2)))
        margin_percent = float(foundry_result.get("margin_percent", round((gross_profit / revenue) * 100, 2) if revenue > 0 else 0.0))
        profit_per_unit = float(foundry_result.get("profit_per_unit", round(price - cost, 2)))
        summary = foundry_result.get(
            "summary",
            f"Unit economics: ₹{price:,.2f} selling price against ₹{cost:,.2f} cost yields ₹{profit_per_unit:,.2f} profit/unit ({margin_percent:.2f}% gross margin)."
        )

        return FinanceResponse(
            revenue=revenue,
            cost_total=cost_total,
            gross_profit=gross_profit,
            margin_percent=margin_percent,
            cost=cost,
            price=price,
            expected_units=units,
            profit_per_unit=profit_per_unit,
            summary=summary
        )
    except Exception as e:
        logger.warning(f"Foundry Finance Agent call failed or not authorized ({e}). Falling back to deterministic calculation.", exc_info=True)
        return _calculate_finance_local(cost, price, units)
