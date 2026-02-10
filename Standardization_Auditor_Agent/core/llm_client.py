import google.generativeai as genai
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
        else:
            genai.configure(api_key=api_key)
        
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=SYSTEM_PROMPT
        )

    async def scan_document(self, content: str, temperature: float = 0.1) -> str:
        """
        使用 Gemini 1.5 Flash 扫描长文档内容，执行格式审计。
        
        Args:
            content: 论文切片或全文内容
            temperature: 生成温度
            
        Returns:
            模型生成的原始文本响应
        """
        try:
            # 针对长文档优化配置
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=8192, # Flash 支持较长输出
            )
            
            # 使用异步生成（如果 SDK 支持 async，目前 google-generativeai 主要为同步/asyncio 封装）
            # 这里演示标准的异步调用方式
            response = await self.model.generate_content_async(
                content,
                generation_config=generation_config
            )
            
            return response.text
            
        except Exception as e:
            # 记录错误日志
            print(f"Gemini API Error: {str(e)}")
            # 返回空字符串或错误提示，避免阻断流程
            return ""
