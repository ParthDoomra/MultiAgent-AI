import sys
import httpx
import json

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


from fastapi.testclient import TestClient
from app.main import app

def test_backend_mvp():
    client = TestClient(app)

    # 1. Health Check: GET /health -> {"status": "ok"}
    res_health = client.get("/health")
    assert res_health.status_code == 200, f"Health check returned {res_health.status_code}"
    health_data = res_health.json()
    assert health_data == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {health_data}"
    print("[PASS] 1. GET /health ->", health_data)

    # 2. Finance Agent: POST /agents/finance
    # Input: {cost: 1500, price: 2999, expected_units: 500}
    # Formulas:
    # revenue = price * expected_units = 2999 * 500 = 1499500.0
    # cost_total = cost * expected_units = 1500 * 500 = 750000.0
    # gross_profit = revenue - cost_total = 749500.0
    # margin_percent = (gross_profit / revenue) * 100 = 49.98
    finance_payload = {"cost": 1500.0, "price": 2999.0, "expected_units": 500}
    res_finance = client.post("/agents/finance", json=finance_payload)
    assert res_finance.status_code == 200, f"Finance agent returned {res_finance.status_code}: {res_finance.text}"
    finance_data = res_finance.json()
    assert finance_data["revenue"] == 1499500.0, f"Unexpected revenue: {finance_data['revenue']}"
    assert finance_data["cost_total"] == 750000.0, f"Unexpected cost_total: {finance_data['cost_total']}"
    assert finance_data["gross_profit"] == 749500.0, f"Unexpected gross_profit: {finance_data['gross_profit']}"
    assert 49.0 <= finance_data["margin_percent"] <= 51.0, f"Unexpected margin_percent: {finance_data['margin_percent']}"
    print("[PASS] 2. POST /agents/finance (Foundry) ->", finance_data)


    # 3. Market Agent: POST /agents/market
    # Input: {product: "smartwatch", target_market: "India"}
    # Output: {market_size: string, competitors: [string], opportunities: [string], risks: [string]}
    market_payload = {"product": "smartwatch", "target_market": "India"}
    res_market = client.post("/agents/market", json=market_payload)
    assert res_market.status_code == 200, f"Market agent returned {res_market.status_code}: {res_market.text}"
    market_data = res_market.json()
    assert isinstance(market_data["market_size"], str), "market_size should be string"
    assert isinstance(market_data["competitors"], list), "competitors should be list"
    assert len(market_data["competitors"]) > 0, "competitors should not be empty"
    assert isinstance(market_data["competitors"][0], str), "competitors should contain strings"
    assert isinstance(market_data["opportunities"], list), "opportunities should be list"
    assert isinstance(market_data["risks"], list), "risks should be list"
    print(f"[PASS] 3. POST /agents/market (Foundry) -> {len(market_data['competitors'])} competitors, {len(market_data['opportunities'])} opportunities")

    # 4. Report Agent: POST /agents/report
    # Input: combined finance + market output
    # Output: {market_potential: string, recommended_price: float, estimated_margin: float, main_risk: string, recommendation: "LAUNCH" | "DO NOT LAUNCH"}
    report_payload = {"finance": finance_data, "market": market_data}
    res_report = client.post("/agents/report", json=report_payload)
    assert res_report.status_code == 200, f"Report agent returned {res_report.status_code}: {res_report.text}"
    report_data = res_report.json()
    assert isinstance(report_data["market_potential"], str)
    assert isinstance(report_data["recommended_price"], float)
    assert isinstance(report_data["estimated_margin"], float)
    assert isinstance(report_data["main_risk"], str)
    assert report_data["recommendation"] in ("LAUNCH", "DO NOT LAUNCH")
    assert report_data["recommendation"] == "LAUNCH"
    print("[PASS] 4. POST /agents/report ->", report_data["recommendation"], f"(margin: {report_data['estimated_margin']}%)")

    # 4b. Sales Agent: POST /agents/sales
    # Input: {finance: {...}, market: {...}}
    # Output: {min_acceptable_price, max_asking_price, recommended_opening_offer, negotiation_strategy, key_talking_points}
    sales_payload = {"finance": finance_data, "market": market_data}
    res_sales = client.post("/agents/sales", json=sales_payload)
    assert res_sales.status_code == 200, f"Sales agent returned {res_sales.status_code}: {res_sales.text}"
    sales_data = res_sales.json()
    assert isinstance(sales_data["min_acceptable_price"], (int, float)) and sales_data["min_acceptable_price"] > 0
    assert isinstance(sales_data["max_asking_price"], (int, float)) and sales_data["max_asking_price"] >= sales_data["min_acceptable_price"]
    assert isinstance(sales_data["recommended_opening_offer"], (int, float))
    assert isinstance(sales_data["negotiation_strategy"], str) and len(sales_data["negotiation_strategy"]) > 0
    assert isinstance(sales_data["key_talking_points"], list) and len(sales_data["key_talking_points"]) > 0
    print("[PASS] 4b. POST /agents/sales (Foundry) ->", f"Min: ₹{sales_data['min_acceptable_price']}, Opening: ₹{sales_data['recommended_opening_offer']}, Max: ₹{sales_data['max_asking_price']}")

    # 4c. Report Agent with Sales Data: POST /agents/report
    report_with_sales_payload = {"finance": finance_data, "market": market_data, "sales": sales_data}
    res_report_sales = client.post("/agents/report", json=report_with_sales_payload)
    assert res_report_sales.status_code == 200, f"Report agent with sales returned {res_report_sales.status_code}: {res_report_sales.text}"
    report_sales_data = res_report_sales.json()
    assert report_sales_data["recommendation"] in ("LAUNCH", "DO NOT LAUNCH")
    print("[PASS] 4c. POST /agents/report (with sales deal strategy) ->", report_sales_data["recommendation"])

    # 5. Orchestrator End-to-End Test (Standard Query):
    orch_query = "Should I launch a smartwatch at ₹2,999 if my manufacturing cost is ₹1,500? I expect to sell 500 units a month"
    res_orch = client.post("/orchestrate", json={"query": orch_query})
    assert res_orch.status_code == 200, f"Orchestrator returned {res_orch.status_code}: {res_orch.text}"
    orch_data = res_orch.json()
    
    assert "agents" in orch_data, "agents field missing from /orchestrate response"
    assert "finance" in orch_data["agents"], "finance agent missing from agents"
    assert "market" in orch_data["agents"], "market agent missing from agents"
    assert "report" in orch_data, "report field missing from /orchestrate response"
    
    orch_fin = orch_data["agents"]["finance"]
    orch_rep = orch_data["report"]
    assert 49.0 <= orch_fin["margin_percent"] <= 51.0, f"Unexpected margin: {orch_fin['margin_percent']}"
    assert orch_rep["recommendation"] == "LAUNCH"
    assert orch_rep["recommended_price"] == 2999.0
    assert 49.0 <= orch_rep["estimated_margin"] <= 51.0, f"Unexpected estimated_margin: {orch_rep['estimated_margin']}"
    print("[PASS] 5. POST /orchestrate End-to-End Success with Foundry Agents!")

    # 6. Orchestrator Negotiation Query: triggers Sales Agent
    orch_negotiate_query = "I am negotiating a bulk deal with a retail distributor for 1,000 smartwatches. Manufacturing cost is ₹1,500 and target price is ₹2,999. What discount and opening offer should I negotiate?"
    res_orch_negotiate = client.post("/orchestrate", json={"query": orch_negotiate_query})
    assert res_orch_negotiate.status_code == 200, f"Orchestrator negotiate returned {res_orch_negotiate.status_code}: {res_orch_negotiate.text}"
    orch_negotiate_data = res_orch_negotiate.json()

    assert "agents" in orch_negotiate_data
    assert "sales" in orch_negotiate_data["agents"], "sales agent should be triggered for negotiation query"
    assert orch_negotiate_data.get("sales") is not None, "top-level sales alias should be populated"
    print("[PASS] 6. POST /orchestrate Negotiation Query triggered Sales Agent successfully!")
    print(f"Sales Agent negotiation strategy: {orch_negotiate_data['sales']['negotiation_strategy'][:120]}...")

if __name__ == "__main__":
    test_backend_mvp()
