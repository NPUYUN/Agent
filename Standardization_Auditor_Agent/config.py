from enum import Enum
from typing import List
import os

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

# LLM Provider: "gemini" or "qwen"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none")
LLM_TIMEOUT_SEC = int(os.getenv("LLM_TIMEOUT_SEC", "8"))

# 数据库配置
# Remote (Default)
# DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")
# Local (Testing) - User: postgres, Pass: Ycc20060308, DB: agent_db
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:Ycc20060308@localhost:5432/agent_db")

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
