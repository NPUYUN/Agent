from pydantic import BaseModel, Field, field_validator, UUID4
from typing import Optional, List
from enum import Enum
from config import ALLOWED_TAGS, AGENT_NAME, AGENT_VERSION

class AuditLevel(str, Enum):
    INFO = "Info"
    WARNING = "Warning"
    CRITICAL = "Critical"

class RequestMetadata(BaseModel):
    paper_id: UUID4 = Field(..., description="论文全局唯一标识 (UUID)")
    paper_title: str = Field(..., description="论文标题", min_length=1)
    chunk_id: str = Field(..., description="切片ID", min_length=1)

class RequestPayload(BaseModel):
    content: str = Field(..., description="论文切片内容", min_length=1)
    context_before: Optional[str] = Field(None, description="前一段落摘要")
    context_after: Optional[str] = Field(None, description="后一段落开头")

class RequestConfig(BaseModel):
    temperature: float = Field(0.1, description="模型温度", ge=0.0, le=1.0)
    max_tokens: int = Field(500, description="最大生成Token数", gt=0)

class AuditRequest(BaseModel):
    """
    审计请求模型
    对应开发规范：API交互规范 - 论文切片上传协议
    """
    request_id: str = Field(..., description="请求ID")
    metadata: RequestMetadata
    payload: RequestPayload
    config: RequestConfig

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req_20231027_001",
                "metadata": {
                    "paper_id": "123e4567-e89b-12d3-a456-426614174000",
                    "paper_title": "论文标题",
                    "chunk_id": "chunk_seq_005"
                },
                "payload": {
                    "content": "论文切片内容...",
                    "context_before": "前文...",
                    "context_after": "后文..."
                },
                "config": {
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            }
        }

class AgentInfo(BaseModel):
    name: str = Field(AGENT_NAME, description="Agent名称")
    version: str = Field(AGENT_VERSION, description="Agent版本")

class AuditResult(BaseModel):
    score: int = Field(..., ge=0, le=100, description="评分")
    audit_level: AuditLevel = Field(..., description="风险等级")
    comment: str = Field(..., description="审计评语")
    suggestion: str = Field(..., description="修改建议")
    tags: List[str] = Field(..., description="问题标签")

    @field_validator('tags')
    def validate_tags(cls, v):
        for tag in v:
            if tag not in ALLOWED_TAGS:
                # 弱校验，仅记录日志或允许通过，遵循"格式至上"原则，但作为Standardization Agent，
                # 我们应当尽可能返回标准tag。此处保留逻辑，不强制报错。
                pass
        return v

class ResourceUsage(BaseModel):
    tokens: int = Field(..., description="Token消耗", ge=0)
    latency_ms: int = Field(..., description="耗时(ms)", ge=0)

class AuditResponse(BaseModel):
    """
    审计响应模型
    对应开发规范：API交互规范 - 审计结果返回协议
    """
    request_id: str = Field(..., description="请求ID")
    agent_info: AgentInfo
    result: AuditResult
    usage: ResourceUsage

    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req_20231027_001",
                "agent_info": {
                    "name": "Standardization_Auditor_Agent",
                    "version": "v1.1"
                },
                "result": {
                    "score": 85,
                    "audit_level": "Warning",
                    "comment": "发现 3 个格式问题。",
                    "suggestion": "建议修正图表标号及错别字。",
                    "tags": ["Citation_Inconsistency", "Label_Missing"]
                },
                "usage": {
                    "tokens": 120,
                    "latency_ms": 1500
                }
            }
        }
