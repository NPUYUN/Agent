from google import genai
from google.genai import types
from typing import Optional
from config import GEMINI_MODEL_NAME, GOOGLE_API_KEY, SYSTEM_PROMPT

class GeminiClient:
    """
    负责与 Google Gemini 模型交互的客户端封装。
    专门用于处理长文档扫描任务，利用 Gemini 1.5 Flash 的长上下文能力。
    """
    def __init__(self, api_key: str = GOOGLE_API_KEY):
        if not api_key:
            # 在实际部署中，可能需要抛出警告或错误，
            # 但为了本地开发不阻塞，这里暂时允许为空，调用时会报错
            print("Warning: GOOGLE_API_KEY is not set.")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)
        
        self.model_name = GEMINI_MODEL_NAME

    async def scan_document(self, content: str, temperature: float = 0.1) -> str:
        """
        使用 Gemini 1.5 Flash 扫描长文档内容，执行格式审计。
        
        Args:
            content: 论文切片或全文内容
            temperature: 生成温度
            
        Returns:
            模型生成的原始文本响应
        """
        if not self.client:
            print("Gemini API Error: Client not initialized (missing API key).")
            return ""

        try:
            # 针对长文档优化配置
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=temperature,
                max_output_tokens=8192, # Flash 支持较长输出
            )
            
            # 使用异步生成
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=content,
                config=config
            )
            
            return response.text
            
        except Exception as e:
            # 记录错误日志
            print(f"Gemini API Error: {str(e)}")
            # 返回空字符串或错误提示，避免阻断流程
            return ""
