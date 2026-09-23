import os
import json
import logging
import re
from typing import Dict, Any, Optional

from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import MessageRole, RunStatus

from app.core.config import settings

logger = logging.getLogger(__name__)

# Cache client and agent IDs
_client_instance: Optional[AgentsClient] = None
_finance_agent_id: Optional[str] = None
_market_agent_id: Optional[str] = None
_report_agent_id: Optional[str] = None
_sales_agent_id: Optional[str] = None
_extractor_agent_id: Optional[str] = None
_chat_agent_id: Optional[str] = None

FINANCE_AGENT_NAME = "finance-agent"
MARKET_AGENT_NAME = "market-agent"
REPORT_AGENT_NAME = "report-agent"
SALES_AGENT_NAME = "sales-agent"
EXTRACTOR_AGENT_NAME = "extractor-agent"
CHAT_AGENT_NAME = "chat-agent"
DEFAULT_FOUNDRY_ENDPOINT = "https://arorapranav0129-3146-resource.services.ai.azure.com/api/projects/arorapranav0129-3146"

EXTRACTOR_AGENT_INSTRUCTIONS = """You are an expert entity extraction agent for a business feasibility analysis system.
Analyze the user's business query or conversation and extract the following parameters as a strict JSON object:

- product (string): The exact product, service, or business idea being discussed (e.g., 'luxury perfume', 'organic matcha tea', 'SaaS project management tool', 'specialty coffee subscription', 'fitness tracker'). Do NOT default to any preset product.
- target_market (string): The geographic region, country, city, or demographic target (e.g., 'Dubai', 'United States', 'India', 'UK', 'Germany', 'Global').
- cost (number or null): The unit manufacturing, procurement, or direct variable cost per item or subscriber. Must be a numeric float without currency symbols (e.g. '$25/bottle' -> 25.0, 'manufacturing cost is ₹1,500' -> 1500.0, 'cost of 10' -> 10.0).
- price (number or null): The target selling price, retail price, or subscription fee per item or subscriber. Must be a numeric float without currency symbols (e.g. '$120/bottle' -> 120.0, 'priced at ₹2,999' -> 2999.0, 'sell for $50' -> 50.0).
- expected_units (integer or null): The projected sales volume, target customers, or units sold per month/batch (e.g. '300 bottles a month' -> 300, '500 units' -> 500, '1,000 subscribers' -> 1000).
- currency (string): The currency symbol or code used in the query (e.g. '$', '₹', '€', '£', 'AED', 'USD', 'INR'). If unspecified, infer from country or default to '$'.
- is_negotiation (boolean): Set to true if the query asks about wholesale deals, vendor discounts, commercial negotiations, retailer margins, or opening offers.

You MUST respond ONLY with a strict JSON object (no markdown code blocks, no backticks, no conversational text) matching this schema:
{
  "product": "<string>",
  "target_market": "<string>",
  "cost": <number or null>,
  "price": <number or null>,
  "expected_units": <integer or null>,
  "currency": "<string>",
  "is_negotiation": <boolean>
}
"""

CHAT_AGENT_INSTRUCTIONS = """You are a senior business launch advisor and strategic consultant.
Given the full business feasibility context (financial unit economics, market competitor analysis, sales deal strategy, and overall launch verdict), provide a direct, insightful, and highly actionable response to the user's follow-up question.

Guidelines:
- Reference exact numbers, margins, and competitor dynamics from the context.
- Provide concrete advice, strategic trade-offs, and practical execution steps.
- Maintain a sharp, executive, clear, and professional tone.
- Do not speak in vague generalities or filler phrases.
"""

FINANCE_AGENT_INSTRUCTIONS = """You are a financial calculation agent for business feasibility analysis.
When given input parameters containing 'cost' (manufacturing/procurement cost per unit), 'price' (target selling price per unit), and 'expected_units' (projected sales volume in units), perform the following financial calculations:

Formulas:
- revenue = price * expected_units
- cost_total = cost * expected_units
- gross_profit = revenue - cost_total
- margin_percent = (gross_profit / revenue) * 100 if revenue > 0 else 0.0
- profit_per_unit = price - cost

You MUST respond ONLY with a strict JSON object (no markdown code blocks, no backticks, no conversational text) matching this schema:
{
  "revenue": <float>,
  "cost_total": <float>,
  "gross_profit": <float>,
  "margin_percent": <float rounded to 2 decimal places>,
  "cost": <float>,
  "price": <float>,
  "expected_units": <int>,
  "profit_per_unit": <float rounded to 2 decimal places>,
  "summary": "<one sentence summarizing unit economics, price, cost, profit/unit and margin>"
}
"""

MARKET_AGENT_INSTRUCTIONS = """You are a market research agent for business feasibility analysis.
When given a product and target_market, research competitors, market size, opportunities, and risks for the given product and target_market, using web search.

You MUST respond ONLY with a strict JSON object (no markdown code blocks, no backticks, no conversational text) matching this schema:
{
  "market_size": "<detailed market size and growth dynamics>",
  "competitors": ["<competitor 1 with price range/positioning>", "<competitor 2 with price range/positioning>", ...],
  "opportunities": ["<growth opportunity 1>", "<growth opportunity 2>", ...],
  "risks": ["<market risk 1>", "<market risk 2>", ...],
  "product": "<product name>",
  "target_market": "<target market>",
  "summary": "<concise summary of market potential and competitive landscape>"
}
"""

SALES_AGENT_INSTRUCTIONS = """You are a sales negotiation and deal strategy agent.
Your objective is to determine an optimal commercial negotiation range and closing strategy for the product.

Inputs:
- 'finance': unit cost, target price, and gross margins (to determine the bottom-line minimum acceptable price without losing money).
- 'market': competitor price ranges, market size, opportunities, and risks (to establish the competitive price ceiling and positioning).

Guidelines:
- min_acceptable_price: float. The absolute lowest price the business can accept on this deal without losing money, ensuring unit cost plus a minimal viable margin buffer is covered.
- max_asking_price: float. The highest defensible opening asking price or list price based on market competitor benchmarks and premium feature differentiation.
- recommended_opening_offer: float. The optimal initial proposal or anchor price to start negotiations, leaving tactical room for concessions while establishing high perceived value.
- negotiation_strategy: string. A strategic overview detailing the concession cadence, deal terms (e.g. volume thresholds, payment terms, co-op marketing, consignment vs firm sale), and walk-away boundary.
- key_talking_points: list of 3-5 persuasive arguments emphasizing margin protection, customer demand, competitor differentiation, and value-add benefits.
- summary: one concise sentence summarizing the sales negotiation stance.

You MUST respond ONLY with a strict JSON object (no markdown code blocks, no backticks, no conversational text) matching this schema:
{
  "min_acceptable_price": <float>,
  "max_asking_price": <float>,
  "recommended_opening_offer": <float>,
  "negotiation_strategy": "<string>",
  "key_talking_points": ["<talking point 1>", "<talking point 2>", ...],
  "summary": "<string>"
}
"""

REPORT_AGENT_INSTRUCTIONS = """You are a senior business decision report agent.
Your role is to synthesize the finance agent outputs, market agent outputs, and optional sales agent outputs into a strategic, data-driven final business recommendation.

When evaluating the proposal:
- Analyze unit economics, projected revenue, costs, and gross margin percentage from the finance output.
- Analyze market size, competitive landscape, growth opportunities, and risks from the market output.
- If 'sales' negotiation output is provided, incorporate the deal parameters (minimum price, opening offer, negotiation strategy, and deal terms) into the strategic advice.
- Formulate a clear recommendation: exactly "LAUNCH" or "DO NOT LAUNCH".
  * If unit economics are healthy (e.g. gross margin >= 20%) and there is viable market potential and manageable risks, recommend "LAUNCH".
  * If margins are critically low/negative (< 20%) or risks and competitive barriers severely outweigh demand, recommend "DO NOT LAUNCH".
- recommended_price must be a float reflecting the recommended selling price per unit.
- estimated_margin must be a float representing the estimated gross profit margin percentage (e.g., 49.97).
- market_potential must be a concise assessment (e.g. "High", "Moderate", "Low").
- main_risk must state the single most critical risk facing this launch.
- summary must be an executive summary explaining the strategic rationale behind the recommendation (including deal/sales negotiation stance if applicable).
- actions must be a list of 3-5 concrete tactical next steps for the business (including sales/commercial milestones if applicable).
- key_factors must be a list of 3-5 critical numerical or strategic factors justifying the decision.

You MUST respond ONLY with a strict JSON object (no markdown code blocks, no backticks, no conversational text) matching this schema:
{
  "market_potential": "<string>",
  "recommended_price": <float>,
  "estimated_margin": <float>,
  "main_risk": "<string>",
  "recommendation": "LAUNCH" | "DO NOT LAUNCH",
  "summary": "<string>",
  "actions": ["<action 1>", "<action 2>", ...],
  "key_factors": ["<factor 1>", "<factor 2>", ...]
}
"""




def get_foundry_endpoint() -> str:
    """Retrieve the Foundry project endpoint from environment or config."""
    return os.getenv("FOUNDRY_PROJECT_ENDPOINT", settings.FOUNDRY_PROJECT_ENDPOINT or DEFAULT_FOUNDRY_ENDPOINT)


def get_foundry_client() -> AgentsClient:
    """
    Initialize and return an AgentsClient using DefaultAzureCredential
    and the configured Foundry project endpoint.
    """
    global _client_instance
    if _client_instance is None:
        endpoint = get_foundry_endpoint()
        logger.info(f"Initializing AgentsClient with endpoint: {endpoint}")
        credential = DefaultAzureCredential()
        _client_instance = AgentsClient(endpoint=endpoint, credential=credential)
    return _client_instance


def get_or_create_extractor_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the extractor-agent in Azure AI Foundry.
    """
    global _extractor_agent_id
    if client is None:
        client = get_foundry_client()

    if _extractor_agent_id:
        try:
            return client.get_agent(agent_id=_extractor_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached extractor agent {_extractor_agent_id}: {e}")
            _extractor_agent_id = None

    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == EXTRACTOR_AGENT_NAME:
                _extractor_agent_id = agent.id
                logger.info(f"Found existing Foundry extractor agent: {_extractor_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{EXTRACTOR_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=EXTRACTOR_AGENT_NAME,
        instructions=EXTRACTOR_AGENT_INSTRUCTIONS,
        description="Extracts product, target market, unit cost, price, and expected volume from user business queries."
    )
    _extractor_agent_id = agent.id
    return agent


def get_or_create_chat_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the chat-agent in Azure AI Foundry.
    """
    global _chat_agent_id
    if client is None:
        client = get_foundry_client()

    if _chat_agent_id:
        try:
            return client.get_agent(agent_id=_chat_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached chat agent {_chat_agent_id}: {e}")
            _chat_agent_id = None

    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == CHAT_AGENT_NAME:
                _chat_agent_id = agent.id
                logger.info(f"Found existing Foundry chat agent: {_chat_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{CHAT_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=CHAT_AGENT_NAME,
        instructions=CHAT_AGENT_INSTRUCTIONS,
        description="Follow-up consultation agent providing deep business advice and answering user questions."
    )
    _chat_agent_id = agent.id
    return agent


def get_or_create_finance_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the finance-agent in Azure AI Foundry.
    Uses model gpt-4.1-mini by default.
    """
    global _finance_agent_id
    if client is None:
        client = get_foundry_client()

    if _finance_agent_id:
        try:
            return client.get_agent(agent_id=_finance_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached finance agent {_finance_agent_id}: {e}")
            _finance_agent_id = None

    # Check if an agent named 'finance-agent' already exists in Foundry
    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == FINANCE_AGENT_NAME:
                _finance_agent_id = agent.id
                logger.info(f"Found existing Foundry finance agent: {_finance_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    # Create new finance agent
    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{FINANCE_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=FINANCE_AGENT_NAME,
        instructions=FINANCE_AGENT_INSTRUCTIONS,
        description="Deterministic financial calculation agent for unit economics and margin assessment."
    )
    _finance_agent_id = agent.id
    logger.info(f"Successfully created Foundry finance agent with ID: {_finance_agent_id}")
    return agent


def get_or_create_market_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the market-agent in Azure AI Foundry.
    Uses model gpt-4.1-mini by default.
    """
    global _market_agent_id
    if client is None:
        client = get_foundry_client()

    if _market_agent_id:
        try:
            return client.get_agent(agent_id=_market_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached market agent {_market_agent_id}: {e}")
            _market_agent_id = None

    # Check if an agent named 'market-agent' already exists in Foundry
    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == MARKET_AGENT_NAME:
                _market_agent_id = agent.id
                logger.info(f"Found existing Foundry market agent: {_market_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    # Create new market agent
    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{MARKET_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=MARKET_AGENT_NAME,
        instructions=MARKET_AGENT_INSTRUCTIONS,
        description="Market research agent for competitor analysis, market sizing, opportunities, and risks."
    )
    _market_agent_id = agent.id
    logger.info(f"Successfully created Foundry market agent with ID: {_market_agent_id}")
    return agent


def get_or_create_report_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the report-agent in Azure AI Foundry.
    Uses model gpt-4.1-mini by default.
    """
    global _report_agent_id
    if client is None:
        client = get_foundry_client()

    if _report_agent_id:
        try:
            return client.get_agent(agent_id=_report_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached report agent {_report_agent_id}: {e}")
            _report_agent_id = None

    # Check if an agent named 'report-agent' already exists in Foundry
    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == REPORT_AGENT_NAME:
                _report_agent_id = agent.id
                logger.info(f"Found existing Foundry report agent: {_report_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    # Create new report agent
    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{REPORT_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=REPORT_AGENT_NAME,
        instructions=REPORT_AGENT_INSTRUCTIONS,
        description="Executive business report agent synthesizing finance and market intelligence into recommendations."
    )
    _report_agent_id = agent.id
    logger.info(f"Successfully created Foundry report agent with ID: {_report_agent_id}")
    return agent


def get_or_create_sales_agent(client: Optional[AgentsClient] = None) -> Any:
    """
    Retrieve or create the sales-agent in Azure AI Foundry.
    Uses model gpt-4.1-mini by default.
    """
    global _sales_agent_id
    if client is None:
        client = get_foundry_client()

    if _sales_agent_id:
        try:
            return client.get_agent(agent_id=_sales_agent_id)
        except Exception as e:
            logger.warning(f"Could not retrieve cached sales agent {_sales_agent_id}: {e}")
            _sales_agent_id = None

    # Check if an agent named 'sales-agent' already exists in Foundry
    try:
        existing_agents = client.list_agents()
        for agent in existing_agents:
            if getattr(agent, "name", None) == SALES_AGENT_NAME:
                _sales_agent_id = agent.id
                logger.info(f"Found existing Foundry sales agent: {_sales_agent_id}")
                return agent
    except Exception as e:
        logger.warning(f"Could not list agents from Foundry: {e}")

    # Create new sales agent
    model_name = os.getenv("FOUNDRY_MODEL", settings.FOUNDRY_MODEL or "gpt-4.1-mini")
    logger.info(f"Creating new Foundry agent '{SALES_AGENT_NAME}' with model '{model_name}'")
    
    agent = client.create_agent(
        model=model_name,
        name=SALES_AGENT_NAME,
        instructions=SALES_AGENT_INSTRUCTIONS,
        description="Sales negotiation and commercial deal strategy agent determining minimum pricing, opening offers, and deal tactics."
    )
    _sales_agent_id = agent.id
    logger.info(f"Successfully created Foundry sales agent with ID: {_sales_agent_id}")
    return agent



def _clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Parse strict JSON from agent response, stripping code blocks if present."""
    text = raw_text.strip()
    # Remove markdown code fences if LLM wrapped it in ```json ... ```
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    return json.loads(text)


def _get_agent_response_text(client: AgentsClient, thread_id: str) -> str:
    """Fetch assistant response text from thread with support for azure-ai-agents roles."""
    agent_role = getattr(MessageRole, "AGENT", "agent")
    try:
        msg_content = client.messages.get_last_message_text_by_role(
            thread_id=thread_id,
            role=agent_role
        )
        if msg_content and getattr(msg_content, "text", None):
            return msg_content.text.value
    except Exception as e:
        logger.debug(f"get_last_message_text_by_role with {agent_role} failed ({e}), falling back to message listing")

    # Fallback to listing messages
    messages = list(client.messages.list(thread_id=thread_id))
    for msg in messages:
        role_val = str(getattr(msg, "role", "")).lower()
        if "agent" in role_val or "assistant" in role_val:
            for content_item in getattr(msg, "content", []):
                if hasattr(content_item, "text") and hasattr(content_item.text, "value"):
                    return content_item.text.value

    raise RuntimeError(f"No agent response found in Foundry thread {thread_id} messages.")


def run_finance_agent_thread(cost: float, price: float, expected_units: int) -> Dict[str, Any]:
    """
    Runs the Finance Agent on Microsoft Foundry via a dedicated thread.
    Returns parsed dictionary conforming to FinanceResponse.
    """
    client = get_foundry_client()
    agent = get_or_create_finance_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for finance-agent: {thread.id}")

    # 2. Add input message to thread
    input_payload = {
        "cost": float(cost),
        "price": float(price),
        "expected_units": int(expected_units)
    }
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=json.dumps(input_payload)
    )

    # 3. Create and process run
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry finance run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Finance Agent run did not complete successfully: {error_detail}")

    # 4. Fetch the agent's assistant response
    raw_text = _get_agent_response_text(client, thread.id)
    return _clean_json_response(raw_text)


def run_market_agent_thread(product: str, target_market: str) -> Dict[str, Any]:
    """
    Runs the Market Agent on Microsoft Foundry via a dedicated thread.
    Returns parsed dictionary conforming to MarketResponse.
    Raises exceptions directly on error so they can be diagnosed.
    """
    client = get_foundry_client()
    agent = get_or_create_market_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for market-agent: {thread.id}")

    # 2. Add input message to thread
    input_payload = {
        "product": str(product),
        "target_market": str(target_market)
    }
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=json.dumps(input_payload)
    )

    # 3. Create and process run
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry market run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Market Agent run did not complete successfully: {error_detail}")

    # 4. Fetch the agent's assistant response
    raw_text = _get_agent_response_text(client, thread.id)
    return _clean_json_response(raw_text)


def run_sales_agent_thread(finance_data: Dict[str, Any], market_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs the Sales Agent on Microsoft Foundry via a dedicated thread.
    Calculates negotiation boundaries, opening offer, and deal strategy based on finance and market inputs.
    Raises exceptions directly on error so they can be diagnosed.
    """
    client = get_foundry_client()
    agent = get_or_create_sales_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for sales-agent: {thread.id}")

    # 2. Add input message to thread
    input_payload = {
        "finance": finance_data,
        "market": market_data
    }
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=json.dumps(input_payload)
    )

    # 3. Create and process run
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry sales run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Sales Agent run did not complete successfully: {error_detail}")

    # 4. Fetch the agent's assistant response
    raw_text = _get_agent_response_text(client, thread.id)
    return _clean_json_response(raw_text)


def run_report_agent_thread(
    finance_data: Dict[str, Any],
    market_data: Dict[str, Any],
    sales_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Runs the Report Agent on Microsoft Foundry via a dedicated thread.
    Synthesizes combined finance, market, and optional sales outputs into a final recommendation.
    Raises exceptions directly on error so they can be diagnosed.
    """
    client = get_foundry_client()
    agent = get_or_create_report_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for report-agent: {thread.id}")

    # 2. Add input message to thread
    input_payload: Dict[str, Any] = {
        "finance": finance_data,
        "market": market_data
    }
    if sales_data:
        input_payload["sales"] = sales_data

    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=json.dumps(input_payload)
    )

    # 3. Create and process run
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry report run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Report Agent run did not complete successfully: {error_detail}")

    # 4. Fetch the agent's assistant response
    raw_text = _get_agent_response_text(client, thread.id)
    return _clean_json_response(raw_text)


def run_extractor_agent_thread(query: str) -> Dict[str, Any]:
    """
    Runs the Extractor Agent on Microsoft Foundry via a dedicated thread.
    Extracts product, target_market, cost, price, expected_units, currency, and is_negotiation.
    """
    client = get_foundry_client()
    agent = get_or_create_extractor_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for extractor-agent: {thread.id}")

    # 2. Add input query message
    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=f"Extract business parameters from this user query:\n\n{query}"
    )

    # 3. Create and process run
    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry extractor run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Extractor Agent run did not complete successfully: {error_detail}")

    # 4. Fetch response
    raw_text = _get_agent_response_text(client, thread.id)
    return _clean_json_response(raw_text)


def run_followup_agent_thread(
    query: str,
    history: list,
    finance_data: Dict[str, Any],
    market_data: Dict[str, Any],
    report_data: Dict[str, Any],
    sales_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Runs the Chat/Consultant Agent on Microsoft Foundry for follow-up conversational queries.
    Provides direct strategic business consultation using the GPT model.
    """
    client = get_foundry_client()
    agent = get_or_create_chat_agent(client)

    # 1. Create a thread
    thread = client.threads.create()
    logger.info(f"Created Foundry thread for chat-agent: {thread.id}")

    # Format context
    history_lines = []
    for turn in history:
        if hasattr(turn, "role") and hasattr(turn, "content"):
            history_lines.append(f"{turn.role}: {turn.content}")
        elif isinstance(turn, dict):
            history_lines.append(f"{turn.get('role')}: {turn.get('content')}")
    history_str = "\n".join(history_lines)

    context_prompt = (
        f"Context from Business Feasibility Analysis:\n"
        f"- Product: {market_data.get('product', 'Specified Business')}\n"
        f"- Target Market: {market_data.get('target_market', 'Target Market')}\n"
        f"- Financials: Price={finance_data.get('price')}, Cost={finance_data.get('cost')}, "
        f"Revenue={finance_data.get('revenue')}, Profit={finance_data.get('gross_profit')}, Margin={finance_data.get('margin_percent')}%\n"
        f"- Market Signals: Market Size={market_data.get('market_size')}, Competitors={market_data.get('competitors')}, "
        f"Opportunities={market_data.get('opportunities')}, Risks={market_data.get('risks')}\n"
    )
    if sales_data:
        context_prompt += (
            f"- Sales Strategy: Min Price={sales_data.get('min_acceptable_price')}, "
            f"Opening Offer={sales_data.get('recommended_opening_offer')}, Max Price={sales_data.get('max_asking_price')}, "
            f"Strategy={sales_data.get('negotiation_strategy')}\n"
        )
    context_prompt += (
        f"- Recommendation Verdict: {report_data.get('recommendation')} - {report_data.get('summary')}\n\n"
        f"Previous Conversation:\n{history_str}\n\n"
        f"User's Question: {query}\n\n"
        f"Please provide a direct, insightful, and strategic answer with concrete numbers and actionable advice."
    )

    client.messages.create(
        thread_id=thread.id,
        role=MessageRole.USER,
        content=context_prompt
    )

    run = client.runs.create_and_process(
        thread_id=thread.id,
        agent_id=agent.id
    )
    logger.info(f"Foundry chat run completed with status: {run.status}")

    if run.status != "completed" and str(run.status) != "RunStatus.COMPLETED":
        error_detail = getattr(run, "last_error", None) or f"Run status is {run.status}"
        raise RuntimeError(f"Foundry Chat Agent run did not complete successfully: {error_detail}")

    raw_text = _get_agent_response_text(client, thread.id)
    return raw_text.strip()


