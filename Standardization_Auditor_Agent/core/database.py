from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, BigInteger, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from typing import AsyncGenerator
import enum
from datetime import datetime
from config import DATABASE_URL
import uuid
import os

from pgvector.sqlalchemy import Vector

Base = declarative_base()

class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"

class PaperSection(Base):
    """
    论文切片存储表 (paper_sections)
    用于存储解析后的论文内容
    """
    __tablename__ = "paper_sections"
    __table_args__ = (UniqueConstraint("paper_id", "chunk_id", name="uq_paper_sections_paper_chunk"),)
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id = Column(UUID(as_uuid=True), index=True, nullable=False, comment="论文ID")
    chunk_id = Column(String, index=True, nullable=False, comment="切片ID")
    section_name = Column(String, comment="章节名称")
    content = Column(Text, nullable=False, comment="切片内容")
    metadata_json = Column(JSONB, default={}, comment="元数据")
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

class ExpertComment(Base):
    """
    专家评语知识库 (expert_comments)
    用于存储量化规则和向量数据
    """
    __tablename__ = "expert_comments"
    
    comment_id = Column(String, primary_key=True, comment="评语唯一ID")
    metric_id = Column(String, index=True, nullable=False, comment="关联指标/规则ID")
    text = Column(Text, nullable=False, comment="专家原始评语内容")
    embedding = Column(Vector(768), nullable=True, comment="向量(768)")
        
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

class AgentRule(Base):
    __tablename__ = "agent_rules"
    __table_args__ = (UniqueConstraint("rule_id", name="uq_agent_rules_rule_id"),)
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    rule_id = Column(String, index=True, nullable=False, comment="规则ID")
    content = Column(Text, nullable=False, comment="规则内容(YAML/JSON字符串)")
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

class ReviewTask(Base):
    """
    任务协同表 (review_tasks)
    严格遵循《开发规范》定义的核心数据表结构
    Ref: 开发规范 - 三、数据库设计规范 - 1. 核心数据表结构 - (3) 任务协同表
    """
    __tablename__ = "review_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="自增主键")
    task_id = Column(String, index=True, nullable=False, comment="对应上传request_id")
    paper_id = Column(UUID(as_uuid=True), index=True, nullable=False, comment="关联论文ID")
    chunk_id = Column(String, nullable=False, comment="切片ID")
    
    agent_name = Column(String, nullable=False, comment="负责审计的Agent名称")
    agent_version = Column(String, nullable=False, comment="审计时的模型/逻辑版本")
    
    status = Column(SAEnum(TaskStatus), default=TaskStatus.PENDING, comment="任务状态")
    
    score = Column(Integer, comment="从result_json冗余的分数")
    audit_level = Column(String, comment="风险等级：Info/Warning/Critical")
    
    result_json = Column(JSONB, comment="Agent返回的完整原始数据")
    error_msg = Column(Text, comment="任务失败时，记录错误堆栈/原因")
    
    usage_tokens = Column(Integer, comment="统计单次任务Token消耗")
    latency_ms = Column(Integer, comment="记录任务耗时")
    
    created_at = Column(TIMESTAMP, default=datetime.utcnow, comment="任务创建时间")
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow, comment="任务最后一次状态变更时间")

class DatabaseManager:
    """
    负责管理数据库连接和会话 (Async SQLAlchemy)
    Ref: 开发规范 - 三、数据库设计规范 - 2. 数据库操作要求
    """
    def __init__(self):
        db_timeout = int(os.getenv("DB_CONNECT_TIMEOUT_SEC", "3"))
        self.engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            future=True,
            pool_pre_ping=True,
            connect_args={"timeout": db_timeout},
        )
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.async_session() as session:
            yield session

    async def close(self):
        await self.engine.dispose()

# 全局 DB 实例
db_manager = DatabaseManager()
