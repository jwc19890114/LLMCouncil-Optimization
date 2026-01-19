"""Configuration for the LLM Council."""

import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# DashScope (Qwen) API key (OpenAI-compatible endpoint)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ApiYi (third-party aggregator, OpenAI-compatible)
APIYI_API_KEY = os.getenv("APIYI_API_KEY")
APIYI_BASE_URL = os.getenv("APIYI_BASE_URL", "https://api.apiyi.com/v1")

# Ollama (local)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Knowledge base (SQLite)
KB_DB_PATH = str(PROJECT_ROOT / "data" / "kb.sqlite")

# Knowledge base - continuous ingestion (optional)
KB_WATCH_ENABLE = os.getenv("KB_WATCH_ENABLE", "").strip().lower() in ("1", "true", "yes", "on")
_KB_WATCH_ROOTS = os.getenv("KB_WATCH_ROOTS", "").strip()
if _KB_WATCH_ROOTS:
    KB_WATCH_ROOTS = [p.strip() for p in _KB_WATCH_ROOTS.replace(";", ",").split(",") if p.strip()]
else:
    # Safe default: a dedicated folder under ./data
    KB_WATCH_ROOTS = [str(PROJECT_ROOT / "data" / "kb_watch")]
KB_WATCH_EXTS = [e.strip().lower().lstrip(".") for e in os.getenv("KB_WATCH_EXTS", "txt,md").split(",") if e.strip()]
KB_WATCH_INTERVAL_SECONDS = max(2, int(os.getenv("KB_WATCH_INTERVAL_SECONDS", "10") or 10))
KB_WATCH_MAX_FILE_MB = max(1, int(os.getenv("KB_WATCH_MAX_FILE_MB", "20") or 20))

# Knowledge base - Hybrid retrieval (optional)
# Embedding model spec: "<provider>:<model>"
KB_EMBEDDING_MODEL = os.getenv("KB_EMBEDDING_MODEL", "")
# Optional rerank model spec (defaults to CHAIRMAN_MODEL if empty)
KB_RERANK_MODEL = os.getenv("KB_RERANK_MODEL", "")

# Council members - list of OpenRouter model identifiers
_COUNCIL_MODELS_ENV = os.getenv("COUNCIL_MODELS")
if _COUNCIL_MODELS_ENV:
    COUNCIL_MODELS = [m.strip() for m in _COUNCIL_MODELS_ENV.split(",") if m.strip()]
else:
    # Model spec format: "<provider>:<model>".
    # Provider can be: openrouter (default), dashscope, apiyi, ollama
    COUNCIL_MODELS = [
        "openrouter:openai/gpt-5.1",
        "openrouter:google/gemini-3-pro-preview",
        "openrouter:anthropic/claude-sonnet-4.5",
        "openrouter:x-ai/grok-4",
    ]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = os.getenv("CHAIRMAN_MODEL", "openrouter:google/gemini-3-pro-preview")

# Title model - generates conversation titles
TITLE_MODEL = os.getenv("TITLE_MODEL", "openrouter:google/gemini-2.5-flash")

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = str(PROJECT_ROOT / "data" / "conversations")
