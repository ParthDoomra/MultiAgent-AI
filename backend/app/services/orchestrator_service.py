import re
import json
import uuid
import logging
from typing import Dict, Any, Tuple, Optional
import httpx
from app.core.config import settings
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

logger = logging.getLogger(__name__)


async def extract_parameters_with_llm(query: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to extract parameters using an LLM API if keys are configured.
    Supports OpenAI, Groq, and Google Gemini.
    """
    system_prompt = (
        "You are an entity extraction system for a business assistant. "
        "Extract the following fields from the user's business query as a strict JSON object:\n"
        "- product (string): name of product\n"
        "- target_market (string): geographic or demographic market (e.g. India, US)\n"
        "- cost (number or null): unit manufacturing or procurement cost\n"
        "- price (number or null): target selling price per unit\n"
        "- expected_units (integer or null): projected sales volume\n\n"
        "Return ONLY the raw JSON object, no markdown, no explanation."
    )

    # 1. Try OpenAI
    if settings.OPENAI_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": settings.LLM_MODEL or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
        except Exception as e:
            logger.warning(f"OpenAI LLM extraction failed: {e}")

    # 2. Try Groq
    if settings.GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    content = res.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
        except Exception as e:
            logger.warning(f"Groq LLM extraction failed: {e}")

    # 3. Try Gemini
    if settings.GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            prompt_text = f"{system_prompt}\n\nUser query: {query}"
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {"response_mime_type": "application/json"}
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text)
        except Exception as e:
            logger.warning(f"Gemini LLM extraction failed: {e}")

    return None


def extract_parameters_regex(query: str) -> Dict[str, Any]:
    """
    Deterministic rule-based and regex parameter extraction fallback.
    Accurately extracts product, target_market, cost, price, and expected_units.
    """
    q = query.lower()
    
    extracted: Dict[str, Any] = {
        "product": "smartwatch",
        "target_market": "India",
        "cost": None,
        "price": None,
        "expected_units": 1000
    }

    # Detect product
    known_products = [
        "smartwatch", "smart watch", "fitness tracker", "fitness band",
        "earbuds", "tws earbuds", "headphones", "phone", "smartphone",
        "laptop", "tablet", "meal-planning service", "meal planning"
    ]
    for p in known_products:
        if p in q:
            extracted["product"] = p
            break
    else:
        # Pattern match: "launch a [product] at/in/with"
        prod_m = re.search(r'(?:launch|start|sell)\s+(?:a|an)?\s*([a-zA-Z\s]{3,30}?)(?:\s+at|\s+priced|\s+in|\s+with|\s+for|\$|₹)', q)
        if prod_m:
            extracted["product"] = prod_m.group(1).strip()

    # Detect target market
    if "₹" in query or "inr" in q or "rupee" in q or "india" in q:
        extracted["target_market"] = "India"
    elif "$" in query or "usd" in q or "us" in q or "usa" in q:
        extracted["target_market"] = "US"
    elif "uk" in q or "london" in q:
        extracted["target_market"] = "UK"

    # Specific country name overrides
    for m in ["india", "us", "usa", "europe", "germany", "japan", "uk"]:
        if re.search(r'\b' + m + r'\b', q):
            extracted["target_market"] = m.capitalize() if m not in ("us", "usa", "uk") else m.upper()
            break

    # 1. Extract expected units first (e.g. "500 units a month", "sell 500 units")
    units_m = re.search(r'([0-9]+(?:,[0-9]+)*)\s*(?:units|pcs|pieces|items)\b', q)
    if units_m:
        extracted["expected_units"] = int(units_m.group(1).replace(",", ""))

    # 2. Extract Cost (e.g. "manufacturing cost is ₹1,500", "cost is 1500", "cost of ₹1,500")
    cost_m = re.search(r'(?:manufacturing\s+cost|unit\s+cost|procurement\s+cost|cost)\s*(?:of|is|at|:)?\s*[₹$Rs\.\s]*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)', q)
    if cost_m:
        extracted["cost"] = float(cost_m.group(1).replace(",", ""))

    # 3. Extract Price
    # Matches: "at ₹2,999", "priced at ₹2,999", "selling price of ₹2,999", "sell at ₹2,999", "price is 2999"
    price_m = re.search(r'(?:priced\s*(?:at|of|is)?|selling\s+price\s*(?:of|is|at|:)?|price\s*(?:of|is|at|:)?|sell\s+(?:at|for)\s*|launch\s+(?:a|an)?\s*[\w\s]{2,25}?\s+at\s+)\s*[₹$Rs\.\s]*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)', q)
    if price_m:
        extracted["price"] = float(price_m.group(1).replace(",", ""))
    else:
        # Check for standalone "at ₹2,999"
        at_m = re.search(r'\bat\s+[₹$Rs\.\s]*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)', q)
        if at_m:
            extracted["price"] = float(at_m.group(1).replace(",", ""))

    # 4. Fallback if currency symbols are present
    # Look for all currency-tagged numbers: ₹1,500 or $2,999
    curr_numbers = re.findall(r'[₹$Rs]\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)', query)
    if curr_numbers:
        parsed_curr = [float(c.replace(",", "")) for c in curr_numbers]
        # If cost is known, price is the other currency value
        if extracted["cost"] is not None and extracted["price"] is None:
            remaining = [p for p in parsed_curr if p != extracted["cost"]]
            if remaining:
                extracted["price"] = remaining[0]
        # If price is known, cost is the other currency value
        elif extracted["price"] is not None and extracted["cost"] is None:
            remaining = [p for p in parsed_curr if p != extracted["price"]]
            if remaining:
                extracted["cost"] = remaining[0]
        # If neither is resolved but 2 currency values exist
        elif extracted["cost"] is None and extracted["price"] is None and len(parsed_curr) >= 2:
            extracted["cost"] = min(parsed_curr)
            extracted["price"] = max(parsed_curr)
        elif extracted["price"] is None and len(parsed_curr) == 1:
            extracted["price"] = parsed_curr[0]


    # Default safeguards
    if extracted["cost"] is None:
        extracted["cost"] = 1500.0
    if extracted["price"] is None:
        extracted["price"] = 2999.0

    return extracted


async def parse_query_and_extract(query: str) -> Tuple[Dict[str, Any], list]:
    """
    Step 1 & Step 2:
    1. Use an LLM call to extract cost, price, expected_units, product, and target_market.
    2. Determine which agents are relevant:
       - finance always if pricing info is present
       - market if a product/market is mentioned
    """
    extracted = await extract_parameters_with_llm(query)
    if not extracted or not extracted.get("product"):
        extracted = extract_parameters_regex(query)
    else:
        # Ensure fallback defaults for any missing critical values
        if extracted.get("cost") is None:
            extracted["cost"] = 1500.0
        else:
            extracted["cost"] = float(extracted["cost"])

        if extracted.get("price") is None:
            extracted["price"] = 2999.0
        else:
            extracted["price"] = float(extracted["price"])

        if not extracted.get("expected_units"):
            extracted["expected_units"] = 500
        else:
            extracted["expected_units"] = int(extracted["expected_units"])

        if not extracted.get("product"):
            extracted["product"] = "smartwatch"
        if not extracted.get("target_market"):
            extracted["target_market"] = "India"

    # Step 2: Determine relevance
    needed_agents = []
    # Finance agent if cost, price, or pricing terminology is present
    if extracted.get("cost") is not None or extracted.get("price") is not None:
        needed_agents.append("finance")

    # Market agent if product or target_market is present
    if extracted.get("product") or extracted.get("target_market"):
        needed_agents.append("market")

    # Sales agent if negotiation, deal, or pricing strategy keywords are present
    sales_keywords = [
        "negotiat", "discount", "deal", "retailer", "distributor", "wholesale",
        "bulk", "b2b", "consignment", "margin split", "pricing strategy",
        "lowest price", "floor price", "asking price", "opening offer",
        "commercial terms", "concession", "sales pitch", "partnership"
    ]
    query_lower = query.lower()
    if any(k in query_lower for k in sales_keywords):
        needed_agents.append("sales")

    # Always ensure at least these two for comprehensive business decision
    if not needed_agents:
        needed_agents = ["finance", "market"]

    return extracted, needed_agents


async def orchestrate_request(
    request: OrchestrateRequest,
    base_url: str = "http://127.0.0.1:8000"
) -> OrchestrateResponse:
    """
    Orchestrator Agent workflow:
    1. Extract cost, price, expected_units, product, target_market from query.
    2. Determine relevant agents (finance, market, sales).
    3. Call relevant agents.
    4. Call report agent with combined outputs (incorporating sales if present).
    5. Return: { agents: { finance: {...}, market: {...}, sales: {...} }, report: {...}, sales: {...} }
    """
    full_context = request.query
    if request.history:
        history_text = "\n".join([f"{turn.role}: {turn.content}" for turn in request.history])
        full_context = f"{history_text}\nuser: {request.query}"

    params, needed_agents = await parse_query_and_extract(full_context)
    
    agents_output: Dict[str, Any] = {}

    # Call Finance Agent if relevant
    if "finance" in needed_agents:
        try:
            finance_payload = FinanceRequest(
                cost=params["cost"],
                price=params["price"],
                expected_units=params["expected_units"]
            )
            fin_res = calculate_finance(finance_payload)
            agents_output["finance"] = fin_res.model_dump()
        except Exception as e:
            logger.warning(f"Direct finance calculation failed: {e}")
            agents_output["finance"] = {
                "revenue": params["price"] * params["expected_units"],
                "cost_total": params["cost"] * params["expected_units"],
                "gross_profit": (params["price"] - params["cost"]) * params["expected_units"],
                "margin_percent": round(((params["price"] - params["cost"]) / params["price"]) * 100, 2),
                "cost": params["cost"],
                "price": params["price"],
                "expected_units": params["expected_units"]
            }
    else:
        # Provide sensible baseline
        agents_output["finance"] = {
            "revenue": params["price"] * params["expected_units"],
            "cost_total": params["cost"] * params["expected_units"],
            "gross_profit": (params["price"] - params["cost"]) * params["expected_units"],
            "margin_percent": round(((params["price"] - params["cost"]) / params["price"]) * 100, 2),
            "cost": params["cost"],
            "price": params["price"],
            "expected_units": params["expected_units"]
        }

    # Call Market Agent if relevant
    if "market" in needed_agents:
        try:
            market_payload = MarketRequest(
                product=params["product"],
                target_market=params["target_market"]
            )
            market_res = analyze_market(market_payload)
            agents_output["market"] = market_res.model_dump()
        except Exception as e:
            logger.warning(f"Direct market analysis failed: {e}")
            agents_output["market"] = {
                "market_size": f"General consumer market in {params['target_market']}",
                "competitors": [],
                "opportunities": ["Standard expansion opportunities"],
                "risks": ["Competitive pricing pressures"]
            }
    else:
        agents_output["market"] = {
            "market_size": f"General consumer market in {params['target_market']}",
            "competitors": [],
            "opportunities": ["Standard expansion opportunities"],
            "risks": ["Competitive pricing pressures"]
        }

    # Call Sales Agent if relevant (e.g. query involves negotiation, deals, discounts)
    if "sales" in needed_agents:
        logger.info("Invoking Sales Agent for commercial negotiation strategy")
        sales_payload = SalesRequest(
            finance=FinanceResponse(**agents_output["finance"]),
            market=MarketResponse(**agents_output["market"])
        )
        sales_res = analyze_sales(sales_payload)
        agents_output["sales"] = sales_res.model_dump()

    # Call Report Agent with combined outputs
    report_payload = ReportRequest(
        finance=FinanceResponse(**agents_output["finance"]),
        market=MarketResponse(**agents_output["market"]),
        sales=SalesResponse(**agents_output["sales"]) if "sales" in agents_output else None
    )
    report_res = generate_business_report(report_payload)
    report_output = report_res.model_dump()

    # Step 5: If this is a follow-up conversation, generate a dedicated direct answer
    followup_answer = None
    if request.history:
        followup_answer = await generate_followup_answer(
            query=request.query,
            history=request.history,
            finance=agents_output.get("finance", {}),
            market=agents_output.get("market", {}),
            sales=agents_output.get("sales"),
            report=report_output
        )

    session_id = request.session_id or str(uuid.uuid4())
    return OrchestrateResponse(
        type="result",
        session_id=session_id,
        message=followup_answer,
        agents=agents_output,
        report=ReportResponse(**report_output),
        finance=agents_output.get("finance"),
        market=agents_output.get("market"),
        sales=agents_output.get("sales")
    )


async def generate_followup_answer(
    query: str,
    history: list,
    finance: dict,
    market: dict,
    report: dict,
    sales: Optional[dict] = None
) -> str:
    """
    Generate an intelligent, researched answer to a follow-up query using LLM if available,
    or deterministic domain knowledge synthesis based on financial, market, and sales findings.
    """
    history_str = "\n".join([f"{t.role}: {t.content}" for t in history])
    sales_info = ""
    if sales:
        sales_info = (
            f"\nSales Negotiation Strategy: Min Price={sales.get('min_acceptable_price')}, "
            f"Max Asking Price={sales.get('max_asking_price')}, "
            f"Opening Offer={sales.get('recommended_opening_offer')}, "
            f"Strategy={sales.get('negotiation_strategy')}, "
            f"Talking Points={sales.get('key_talking_points')}\n"
        )

    prompt = (
        f"You are a top-tier business launch analyst and commercial deal strategist.\n"
        f"Previous conversation context:\n{history_str}\n\n"
        f"Latest User Follow-up Question: '{query}'\n\n"
        f"Current Financial Calculation: Revenue={finance.get('revenue')}, Cost Total={finance.get('cost_total')}, Gross Profit={finance.get('gross_profit')}, Margin={finance.get('margin_percent')}%, Price={finance.get('price')}, Cost={finance.get('cost')}\n"
        f"Market Research Signals: Competitors={market.get('competitors')}, Opportunities={market.get('opportunities')}, Risks={market.get('risks')}\n"
        f"{sales_info}"
        f"Synthesized Recommendation: {report.get('recommendation')} - {report.get('summary')}\n\n"
        f"Provide a direct, concise, and insightful answer (2-3 paragraphs or clear bullet points) that directly answers the user's question with specific numbers, competitive tradeoffs, and strategic advice. Do not output generic boilerplate."
    )

    # 1. Try OpenAI
    if settings.OPENAI_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": settings.LLM_MODEL or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a senior business launch analyst. Answer directly with clarity, data, and actionable strategic advice."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    return res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"OpenAI follow-up synthesis failed: {e}")

    # 2. Try Groq
    if settings.GROQ_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are a senior business launch analyst. Answer directly with clarity, data, and actionable strategic advice."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                if res.status_code == 200:
                    return res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Groq follow-up synthesis failed: {e}")

    # 3. Try Gemini
    if settings.GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            async with httpx.AsyncClient(timeout=12.0) as client:
                res = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                if res.status_code == 200:
                    return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.warning(f"Gemini follow-up synthesis failed: {e}")

    # Deterministic contextual synthesis fallback
    q_lower = query.lower()
    margin = finance.get("margin_percent", 0.0)
    price = finance.get("price", 0.0)
    cost = finance.get("cost", 0.0)
    main_risk = report.get("main_risk", market.get("risks", ["Market competition"])[0] if market.get("risks") else "Competitive pressure")

    if "lower" in q_lower or "discount" in q_lower or "20%" in q_lower or "drop" in q_lower:
        new_price = round(price * 0.8, 2)
        new_margin = round(((new_price - cost) / new_price) * 100, 2) if new_price > 0 else 0.0
        return (
            f"If you reduce the target price by 20% to ₹{new_price:,.2f}:\n\n"
            f"• **Unit Economics Impact**: Your gross margin drops from {margin}% to {new_margin}%. Profit per unit decreases from ₹{(price - cost):,.2f} to ₹{(new_price - cost):,.2f}.\n"
            f"• **Competitive Position**: A ₹{new_price:,.2f} price point makes you significantly more competitive against entry-level incumbents.\n"
            f"• **Strategic Recommendation**: Only pursue this price reduction if volume increases by at least {max(15, int(100 - new_margin))}% to offset the tighter gross margin buffer."
        )
    elif "risk" in q_lower or "mitigate" in q_lower or "protect" in q_lower:
        competitor_names = ", ".join([c.split(" (")[0] for c in market.get("competitors", [])[:2]])
        return (
            f"To mitigate your primary risk ({main_risk}):\n\n"
            f"1. **Supplier Negotiation**: Lock in tiered unit volume discounts to safeguard your {margin}% margin against ad-spend fluctuations.\n"
            f"2. **Differentiated Value Proposition**: Instead of competing solely on price against {competitor_names or 'established brands'}, highlight clear differentiators (e.g. build quality, warranty, or software experience).\n"
            f"3. **Controlled Pilot**: Run a measured pilot of 300–500 units to test product return rates and organic reviews before full-scale inventory commitment."
        )
    elif "double" in q_lower or "volume" in q_lower or "1,000" in q_lower or "1000" in q_lower or "scale" in q_lower:
        scaled_units = finance.get("expected_units", 500) * 2
        scaled_revenue = price * scaled_units
        scaled_profit = (price - cost) * scaled_units
        return (
            f"Scaling volume to {scaled_units:,} units/month significantly enhances financial returns:\n\n"
            f"• **Revenue Projection**: Monthly revenue reaches ₹{scaled_revenue:,.2f} with total gross profit of ₹{scaled_profit:,.2f}.\n"
            f"• **Operational Leverage**: Doubling volume typically unlocks better procurement rates from suppliers, further expanding your {margin}% margin.\n"
            f"• **Key Prerequisite**: Ensure your customer acquisition cost (CAC) remains tightly managed as you scale digital advertising campaigns."
        )
    else:
        return (
            f"Regarding your question '{query}':\n\n"
            f"• **Current Assessment**: With a selling price of ₹{price:,.2f} and {margin}% margin, your unit economics are in a strong {report.get('recommendation', 'LAUNCH')} position.\n"
            f"• **Market Context**: Watch out for {main_risk} and monitor key competitor moves closely.\n"
            f"• **Strategic Next Step**: Validate customer demand with pre-orders to verify conversion rates before expanding batch sizes."
        )
