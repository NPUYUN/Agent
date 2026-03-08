from google import genai
from google.genai import types
from openai import AsyncOpenAI
from typing import Optional
from config import (
    GEMINI_MODEL_NAME, GOOGLE_API_KEY,
    QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL_NAME,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_NAME,
    LLM_PROVIDER, LLM_TIMEOUT_SEC
)
from core.prompts import SYSTEM_PROMPT_MAIN as SYSTEM_PROMPT

class LLMClient:
    """
    统一的 LLM 客户端封装，支持 Google Gemini 和 Qwen (DashScope)。
    根据 config.LLM_PROVIDER 动态切换后端。
    """
    def __init__(self):
        self.provider = LLM_PROVIDER.lower() if LLM_PROVIDER else "none"
        
        # 初始化 Gemini
        if self.provider == "gemini":
            if not GOOGLE_API_KEY:
                self.gemini_client = None
                self.provider = "none"
            else:
                self.gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
            self.model_name = GEMINI_MODEL_NAME
            
        # 初始化 Qwen (OpenAI Compatible)
        elif self.provider == "qwen":
            if not QWEN_API_KEY:
                self.qwen_client = None
                self.provider = "none"
            else:
                self.qwen_client = AsyncOpenAI(
                    api_key=QWEN_API_KEY,
                    base_url=QWEN_BASE_URL
                )
            self.model_name = QWEN_MODEL_NAME
        
        # 初始化 DeepSeek (OpenAI Compatible)
        elif self.provider == "deepseek":
            if not DEEPSEEK_API_KEY:
                self.deepseek_client = None
                self.provider = "none"
            else:
                self.deepseek_client = AsyncOpenAI(
                    api_key=DEEPSEEK_API_KEY,
                    base_url=DEEPSEEK_BASE_URL
                )
            self.model_name = DEEPSEEK_MODEL_NAME

        else:
            self.provider = "none"

    async def scan_document(self, content: str, temperature: float = 0.1) -> str:
        """
        扫描文档内容，执行格式审计。
        """
        if self.provider == "gemini":
            return await self._scan_with_gemini(content, temperature)
        elif self.provider == "qwen":
            return await self._scan_with_qwen(content, temperature)
        elif self.provider == "deepseek":
            return await self._scan_with_deepseek(content, temperature)
        else:
            return ""

    async def _scan_with_gemini(self, content: str, temperature: float) -> str:
        if not self.gemini_client:
            return ""

        try:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=temperature,
                max_output_tokens=8192,
            )
            
            response = await self.gemini_client.aio.models.generate_content(
                model=self.model_name,
                contents=content,
                config=config
            )
            return response.text
        except Exception as e:
            print(f"LLM Error (Gemini): {e}", flush=True)
            import traceback
            traceback.print_exc()
            return ""

    async def _scan_with_qwen(self, content: str, temperature: float) -> str:
        if not self.qwen_client:
            return ""

        try:
            response = await self.qwen_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                temperature=temperature,
                max_tokens=2000, # Qwen max output limitation
                timeout=LLM_TIMEOUT_SEC,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error (Qwen): {e}", flush=True)
            import traceback
            traceback.print_exc()
            return ""

    async def _scan_with_deepseek(self, content: str, temperature: float) -> str:
        if not self.deepseek_client:
            return ""

        try:
            response = await self.deepseek_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content}
                ],
                temperature=temperature,
                max_tokens=4096, # DeepSeek V3 supports longer context
                timeout=LLM_TIMEOUT_SEC,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM Error (DeepSeek): {e}", flush=True)
            import traceback
            traceback.print_exc()
            return ""

# 为了兼容旧代码，保留 GeminiClient 别名，但建议迁移到 LLMClient
GeminiClient = LLMClient
