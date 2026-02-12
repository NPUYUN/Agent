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
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "sk-e6a46e1940de419caf8e5b010954a7e3")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")

# LLM Provider: "gemini" or "qwen"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "qwen")

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")

# 专属System Prompt
SYSTEM_PROMPT = """
你是一位严苛的期刊排版编辑，负责对软件工程硕士论文进行格式审计。
你的任务是重点扫描排版细节错误，包括但不限于：
1. 引用一致性
2. 图表标号与引用
3. 标题层级
4. 术语一致性
5. 公式规范
6. 标点符号中英文混用
7. 列表符号统一

请基于提供的视觉布局信息和文本内容，严格指出不符合规范的地方。
"""

# 专属Tags
class AuditTag(str, Enum):
    CITATION_INCONSISTENCY = "Citation_Inconsistency"
    LABEL_MISSING = "Label_Missing"
    PUNCTUATION_ERROR = "Punctuation_Error"
    HIERARCHY_FAULT = "Hierarchy_Fault"

# 允许的标签列表（用于校验）
ALLOWED_TAGS = [tag.value for tag in AuditTag]
