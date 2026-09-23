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
from app.services.foundry_client import (
    run_extractor_agent_thread,
    run_followup_agent_thread,
)

logger = logging.getLogger(__name__)


def extract_parameters_with_foundry(query: str) -> Optional[Dict[str, Any]]:
    """
    Extract business parameters using the Azure AI Foundry Extractor Agent powered by the GPT model.
    """
    try:
        logger.info(f"Extracting parameters via Foundry Extractor Agent for query: '{query[:80]}...'")
        result = run_extractor_agent_thread(query)
        if result and isinstance(result, dict) and result.get("product"):
            logger.info(f"Foundry Extractor Agent successfully extracted: {result}")
            return result
    except Exception as e:
        logger.warning(f"Foundry Extractor Agent extraction failed: {e}")
    return None


async def extract_parameters_with_external_llm(query: str) -> Optional[Dict[str, Any]]:
    """
    Fallback extraction using direct OpenAI/Groq/Gemini if API keys are configured.
    """
    system_prompt = (
        "You are an entity extraction system for a business assistant. "
        "Extract the following fields from the user's business query as a strict JSON object:\n"
        "- product (string): exact name or description of product/service\n"
        "- target_market (string): geographic or demographic market (e.g. Dubai, US, India, UK)\n"
        "- cost (number or null): unit manufacturing or procurement cost\n"
        "- price (number or null): target selling price per unit\n"
        "- expected_units (integer or null): projected sales volume\n"
        "- currency (string): currency symbol (e.g. $, ₹, £, €). If pricing or currency is explicitly given in the query, use that exact currency only. If currency or price is not specified, you MUST default strictly to '₹' (Indian Rupee / INR).\n"
        "- is_negotiation (boolean): true if query involves deals, discounts, wholesale, commercial terms\n\n"
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
    Dynamic rule-based and regex parameter extraction fallback.
    Accurately extracts product, target_market, cost, price, expected_units, and currency.
    """
    q = query.lower()
    
    extracted: Dict[str, Any] = {
        "product": "",
        "target_market": "India",
        "cost": None,
        "price": None,
        "expected_units": 500,
        "currency": "₹",
        "is_negotiation": False
    }

    # 1. Detect explicit currency
    if "$" in query or "usd" in q or "dollar" in q:
        extracted["currency"] = "$"
        extracted["target_market"] = "US"
    elif "£" in query or "gbp" in q or "pound" in q:
        extracted["currency"] = "£"
        extracted["target_market"] = "UK"
    elif "€" in query or "eur" in q or "euro" in q:
        extracted["currency"] = "€"
        extracted["target_market"] = "Europe"
    elif "aed" in q or "dirham" in q:
        extracted["currency"] = "AED"
        extracted["target_market"] = "Dubai"
    elif "₹" in query or "inr" in q or "rupee" in q or "rs." in q or "rs " in q:
        extracted["currency"] = "₹"
        extracted["target_market"] = "India"
    else:
        # Standard default currency: Indian Rupee (₹)
        extracted["currency"] = "₹"
        extracted["target_market"] = "India"

    # 2. Detect explicit target market mentions
    market_map = {
        "dubai": "Dubai",
        "uae": "UAE",
        "india": "India",
        "us": "US",
        "usa": "US",
        "united states": "United States",
        "uk": "UK",
        "london": "London",
        "portland": "Portland",
        "seattle": "Seattle",
        "germany": "Germany",
        "europe": "Europe",
        "canada": "Canada",
        "australia": "Australia",
        "singapore": "Singapore",
        "japan": "Japan"
    }
    for key, val in market_map.items():
        if re.search(r'\b' + re.escape(key) + r'\b', q):
            extracted["target_market"] = val
            break

    # 3. Dynamic Product Extraction
    # Remove leading action prefixes
    clean_q = re.sub(
        r'^(?:should i|can i|i want to|planning to|how about|what if i|is it profitable to)?\s*(?:launch|start|sell|create|build|open|introduce|run)\s+(?:a|an|the)?\s*',
        '',
        query,
        flags=re.IGNORECASE
    ).strip()

    # Match product before prepositions like "in [market]", "at [price]", "priced at", "for [price]", "with [cost]"
    prod_match = re.search(
        r'^([a-zA-Z0-9\s\-]+?)(?:\s+(?:in|at|for|priced at|with|targeting|costing|selling)\s+[\$₹£€0-9a-zA-Z]|\s*[\$₹£€]|\?|$)',
        clean_q,
        flags=re.IGNORECASE
    )
    if prod_match:
        cand = prod_match.group(1).strip()
        # Filter out filler words
        if cand.lower() not in ("business", "service", "company", "idea", "product", "it") and len(cand) >= 3:
            extracted["product"] = cand

    if not extracted["product"]:
        # Fallback keyword checks
        for p in ["smartwatch", "fitness tracker", "perfume", "coffee", "earbuds", "meal-planning service", "saas", "clothing", "skincare"]:
            if p in q:
                extracted["product"] = p
                break

    if not extracted["product"]:
        extracted["product"] = "New Business Venture"

    # 4. Extract expected units
    units_m = re.search(r'([0-9]+(?:,[0-9]+)*)\s*(?:units|pcs|pieces|items|bottles|subscribers|customers|clients|orders|sales|users|boxes)\b', q)
    if units_m:
        extracted["expected_units"] = int(units_m.group(1).replace(",", ""))

    # 5. Extract Cost
    cost_m = re.search(
        r'(?:manufacturing\s+cost|procurement\s+cost|unit\s+cost|cost\s+of|cost\s+is|cost\s*:|cost)\s*(?:of|is|at|:)?\s*[\$₹£€Rs\.\s]*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)',
        q
    )
    if cost_m:
        extracted["cost"] = float(cost_m.group(1).replace(",", ""))

    # 6. Extract Price
    price_m = re.search(
        r'(?:priced\s*(?:at|of|is)?|selling\s+price\s*(?:of|is|at|:)?|selling\s+for|price\s*(?:of|is|at|:)?|sell\s+(?:at|for)\s*|at\s*[\$₹£€Rs\.]+|for\s+[\$₹£€Rs\.]+|at\s+|for\s+)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)\s*(?:per|\/|each|\b)',
        q
    )
    if price_m:
        extracted["price"] = float(price_m.group(1).replace(",", ""))

    # 7. Fallback currency number matching if price/cost still unresolved
    all_currencies = re.findall(r'(?:[\$₹£€]|(?:rs\.?|inr|usd|gbp|eur|aed)\s*)\s*([0-9]+(?:,[0-9]+)*(?:\.[0-9]+)?)', query, re.IGNORECASE)
    if all_currencies:
        nums = [float(n.replace(",", "")) for n in all_currencies]
        if extracted["cost"] is None and extracted["price"] is None:
            if len(nums) >= 2:
                extracted["cost"] = min(nums)
                extracted["price"] = max(nums)
            elif len(nums) == 1:
                extracted["price"] = nums[0]
        elif extracted["price"] is not None and extracted["cost"] is None:
            remaining = [n for n in nums if n != extracted["price"]]
            if remaining:
                extracted["cost"] = remaining[0]
        elif extracted["cost"] is not None and extracted["price"] is None:
            remaining = [n for n in nums if n != extracted["cost"]]
            if remaining:
                extracted["price"] = remaining[0]

    # Defaults for financial stability if user didn't specify numbers
    if extracted["cost"] is None and extracted["price"] is None:
        if extracted["currency"] == "$":
            extracted["cost"] = 25.0
            extracted["price"] = 60.0
        elif extracted["currency"] == "£":
            extracted["cost"] = 20.0
            extracted["price"] = 50.0
        elif extracted["currency"] == "€":
            extracted["cost"] = 22.0
            extracted["price"] = 55.0
        elif extracted["currency"] == "AED":
            extracted["cost"] = 90.0
            extracted["price"] = 220.0
        else: # Indian Rupee ₹ / standard default
            extracted["cost"] = 1500.0
            extracted["price"] = 2999.0
    elif extracted["cost"] is None and extracted["price"] is not None:
        extracted["cost"] = round(extracted["price"] * 0.4, 2)
    elif extracted["price"] is None and extracted["cost"] is not None:
        extracted["price"] = round(extracted["cost"] * 2.2, 2)

    return extracted


async def parse_query_and_extract(query: str) -> Tuple[Dict[str, Any], list]:
    """
    Step 1 & Step 2:
    1. First use Azure AI Foundry Extractor Agent (or external LLM) to accurately extract product, market, cost, price.
    2. Fallback to smart regex extraction.
    3. Determine which agents are relevant (finance, market, sales).
    """
    # 1. Try Foundry Extractor Agent (powered by configured GPT model)
    extracted = extract_parameters_with_foundry(query)

    # 2. If not found, try external LLMs if configured
    if not extracted or not extracted.get("product"):
        extracted = await extract_parameters_with_external_llm(query)

    # 3. Always run regex extraction as baseline / fallback
    regex_extracted = extract_parameters_regex(query)

    if not extracted:
        extracted = regex_extracted
    else:
        # Merge to ensure complete fields
        if not extracted.get("product") or extracted.get("product") in ("None", "null"):
            extracted["product"] = regex_extracted.get("product", "New Venture")
        if not extracted.get("target_market") or extracted.get("target_market") in ("None", "null"):
            extracted["target_market"] = regex_extracted.get("target_market", "India")
        # If no explicit foreign currency was provided in query, standard currency is strictly Indian Rupee (₹)
        has_explicit_foreign_currency = any(
            sym in query.lower() for sym in ["$", "usd", "dollar", "£", "gbp", "pound", "€", "eur", "euro", "aed", "dirham"]
        )
        if not has_explicit_foreign_currency:
            extracted["currency"] = "₹"
        elif not extracted.get("currency") or extracted.get("currency") == "₹":
            extracted["currency"] = regex_extracted.get("currency", "$")
        if extracted.get("cost") is None:
            extracted["cost"] = regex_extracted.get("cost", 1500.0 if extracted.get("currency") == "₹" else 25.0)
        else:
            extracted["cost"] = float(extracted["cost"])
        if extracted.get("price") is None:
            extracted["price"] = regex_extracted.get("price", 2999.0 if extracted.get("currency") == "₹" else 60.0)
        else:
            extracted["price"] = float(extracted["price"])
        if not extracted.get("expected_units"):
            extracted["expected_units"] = regex_extracted.get("expected_units", 500)
        else:
            extracted["expected_units"] = int(extracted["expected_units"])

    logger.info(
        f"Final Extracted Query Parameters: Product='{extracted.get('product')}', "
        f"Market='{extracted.get('target_market')}', Price={extracted.get('price')}, "
        f"Cost={extracted.get('cost')}, Units={extracted.get('expected_units')}, Currency={extracted.get('currency')}"
    )

    # Step 2: Determine relevance - all three core agents are always active
    needed_agents = ["finance", "market", "sales"]

    return extracted, needed_agents


async def orchestrate_request(
    request: OrchestrateRequest,
    base_url: str = "http://127.0.0.1:8000"
) -> OrchestrateResponse:
    """
    Orchestrator Agent workflow:
    1. Extract cost, price, expected_units, product, target_market from query using Foundry Extractor Agent.
    2. Determine relevant agents (finance, market, sales).
    3. Call relevant Foundry agents.
    4. Call Foundry report agent with combined outputs (incorporating sales if present).
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
                "margin_percent": round(((params["price"] - params["cost"]) / params["price"]) * 100, 2) if params["price"] > 0 else 0.0,
                "cost": params["cost"],
                "price": params["price"],
                "expected_units": params["expected_units"]
            }
    else:
        agents_output["finance"] = {
            "revenue": params["price"] * params["expected_units"],
            "cost_total": params["cost"] * params["expected_units"],
            "gross_profit": (params["price"] - params["cost"]) * params["expected_units"],
            "margin_percent": round(((params["price"] - params["cost"]) / params["price"]) * 100, 2) if params["price"] > 0 else 0.0,
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
                "market_size": f"General consumer market for {params['product']} in {params['target_market']}",
                "competitors": [],
                "opportunities": ["Standard market expansion opportunities"],
                "risks": ["Competitive pricing pressures"]
            }
    else:
        agents_output["market"] = {
            "market_size": f"General consumer market for {params['product']} in {params['target_market']}",
            "competitors": [],
            "opportunities": ["Standard market expansion opportunities"],
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
            report=report_output,
            currency=params.get("currency", "₹")
        )

    session_id = request.session_id or str(uuid.uuid4())
    return OrchestrateResponse(
        type="result",
        session_id=session_id,
        currency=params.get("currency", "₹"),
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
    sales: Optional[dict] = None,
    currency: str = "₹"
) -> str:
    """
    Generate an intelligent, researched answer to a follow-up query using Azure AI Foundry Chat Agent,
    external LLMs, or dynamic domain knowledge synthesis based on financial, market, and sales findings.
    """
    # 1. Try Azure AI Foundry Chat Agent (powered by configured GPT model)
    try:
        logger.info(f"Generating follow-up answer via Foundry Chat Agent for query: '{query[:80]}...'")
        foundry_chat_response = run_followup_agent_thread(
            query=query,
            history=history,
            finance_data=finance,
            market_data=market,
            report_data=report,
            sales_data=sales
        )
        if foundry_chat_response and len(foundry_chat_response.strip()) > 20:
            logger.info("Successfully generated follow-up answer via Foundry Chat Agent")
            return foundry_chat_response.strip()
    except Exception as e:
        logger.warning(f"Foundry Chat Agent follow-up failed: {e}")

    history_str = "\n".join([f"{t.role if hasattr(t, 'role') else t.get('role')}: {t.content if hasattr(t, 'content') else t.get('content')}" for t in history])
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

    # 2. Try OpenAI
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

    # 3. Try Groq
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

    # 4. Try Gemini
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
    curr = currency or "₹"
    main_risk = report.get("main_risk", market.get("risks", ["Market competition"])[0] if market.get("risks") else "Competitive pressure")

    if "lower" in q_lower or "discount" in q_lower or "20%" in q_lower or "drop" in q_lower or "cut" in q_lower:
        new_price = round(price * 0.8, 2)
        new_margin = round(((new_price - cost) / new_price) * 100, 2) if new_price > 0 else 0.0
        return (
            f"If you reduce the target price by 20% to {curr}{new_price:,.2f}:\n\n"
            f"• **Unit Economics Impact**: Your gross margin drops from {margin}% to {new_margin}%. Profit per unit decreases from {curr}{(price - cost):,.2f} to {curr}{(new_price - cost):,.2f}.\n"
            f"• **Competitive Position**: A {curr}{new_price:,.2f} price point makes you significantly more competitive against entry-level incumbents.\n"
            f"• **Strategic Recommendation**: Only pursue this price reduction if volume increases by at least {max(15, int(100 - new_margin))}% to offset the tighter gross margin buffer."
        )
    elif "risk" in q_lower or "mitigate" in q_lower or "protect" in q_lower:
        competitor_names = ", ".join([str(c).split(" (")[0] for c in market.get("competitors", [])[:2]])
        return (
            f"To mitigate your primary risk ({main_risk}):\n\n"
            f"1. **Supplier Negotiation**: Lock in tiered unit volume discounts to safeguard your {margin}% margin against operational fluctuations.\n"
            f"2. **Differentiated Value Proposition**: Instead of competing solely on price against {competitor_names or 'established brands'}, highlight clear differentiators (e.g. build quality, warranty, or software experience).\n"
            f"3. **Controlled Pilot**: Run a measured pilot batch to test customer return rates and organic reviews before full-scale inventory commitment."
        )
    elif "double" in q_lower or "volume" in q_lower or "scale" in q_lower or "1000" in q_lower:
        scaled_units = finance.get("expected_units", 500) * 2
        scaled_revenue = price * scaled_units
        scaled_profit = (price - cost) * scaled_units
        return (
            f"Scaling volume to {scaled_units:,} units significantly enhances financial returns:\n\n"
            f"• **Revenue Projection**: Revenue reaches {curr}{scaled_revenue:,.2f} with total gross profit of {curr}{scaled_profit:,.2f}.\n"
            f"• **Operational Leverage**: Doubling volume typically unlocks better procurement rates from suppliers, further expanding your {margin}% margin.\n"
            f"• **Key Prerequisite**: Ensure your customer acquisition cost (CAC) remains tightly managed as you scale marketing campaigns."
        )
    else:
        return (
            f"Regarding your question '{query}':\n\n"
            f"• **Current Assessment**: With a selling price of {curr}{price:,.2f} and {margin}% margin, your unit economics are in a strong {report.get('recommendation', 'LAUNCH')} position.\n"
            f"• **Market Context**: Watch out for {main_risk} and monitor key competitor moves closely.\n"
            f"• **Strategic Next Step**: Validate customer demand with pre-orders to verify conversion rates before expanding batch sizes."
        )

