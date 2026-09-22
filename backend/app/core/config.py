from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Multi-Agent Business Assistant API"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"
    
    # CORS Configuration - allow all origins for dev/external apps
    CORS_ORIGINS: List[str] = ["*"]
    
    # Active MVP Agents
    ACTIVE_AGENTS: List[str] = [
        "orchestrator",
        "finance",
        "market",
        "sales",
        "report",
    ]


    # Azure AI Foundry configuration
    FOUNDRY_PROJECT_ENDPOINT: str = "https://arorapranav0129-3146-resource.services.ai.azure.com/api/projects/arorapranav0129-3146"
    FOUNDRY_MODEL: str = "gpt-4.1-mini"

    # Optional LLM configuration
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o-mini"

    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings()

