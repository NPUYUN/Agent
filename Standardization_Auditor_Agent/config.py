from enum import Enum
from typing import List
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)
load_dotenv(override=False)

# Agent基本信息
AGENT_NAME = "Standardization_Auditor_Agent"
AGENT_VERSION = "v1.1"  # Updated version

# 环境配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# LLM 配置
GEMINI_MODEL_NAME = "gemini-1.5-flash"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")  # 从环境变量获取 API Key

# Qwen 配置 (DashScope Compatible)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")

# LLM Provider: "gemini", "qwen" or "deepseek"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_TIMEOUT_SEC = int(os.getenv("LLM_TIMEOUT_SEC", "60"))

# RAG / Embedding 配置
SBERT_MODEL_NAME = os.getenv("SBERT_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
SBERT_DEVICE = os.getenv("SBERT_DEVICE", "")

# 布局分析配置
LAYOUT_ANALYSIS_TIMEOUT = int(os.getenv("LAYOUT_ANALYSIS_TIMEOUT", "300")) # 5分钟，适应长文档处理

# 数据库配置
# Remote (Default)
# DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/agent_db")

# 专属System Prompt (Moved to core/prompts.py)
# SYSTEM_PROMPT = "..."

# 专属Tags
class AuditTag(str, Enum):
    CITATION_INCONSISTENCY = "Citation_Inconsistency"
    LABEL_MISSING = "Label_Missing"
    PUNCTUATION_ERROR = "Punctuation_Error"
    HIERARCHY_FAULT = "Hierarchy_Fault"

# 允许的标签列表（用于校验）
ALLOWED_TAGS = [tag.value for tag in AuditTag]
