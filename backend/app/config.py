import os

from dotenv import load_dotenv

load_dotenv()

CH_API_KEY: str = os.environ.get("CH_API_KEY", "")
CH_USE_FIXTURES: bool = os.environ.get("CH_USE_FIXTURES", "true").lower() not in ("false", "0", "no")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "anthropic/claude-sonnet-4-5")
