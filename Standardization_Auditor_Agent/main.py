import os
import sys
import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from models import AuditRequest, AuditResponse, AgentInfo, AuditResult, ResourceUsage, AuditLevel
from core.layout_analysis import LayoutAnalyzer
from api.layout_routes import router as layout_router
from core.semantic_check import SemanticChecker
from core.database import db_manager, ReviewTask, TaskStatus
from core.rule_engine import RuleEngine
from utils.logger import setup_logger
from config import AGENT_NAME, AGENT_VERSION, AuditTag

# 初始化日志
logger = setup_logger(AGENT_NAME)

# 初始化规则引擎
rule_engine = RuleEngine()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：连接数据库
    logger.info("Starting up: Connecting to database...")
    # await db_manager.engine.connect() # SQLAlchemy async engine is lazy
    logger.info("Rules loaded: %s", list(rule_engine.rules.keys()))
    yield
    # 关闭时：断开数据库
    logger.info("Shutting down: Closing database connection...")
    await db_manager.close()

app = FastAPI(title=AGENT_NAME, version=AGENT_VERSION, lifespan=lifespan)
app.include_router(layout_router)

# 初始化核心组件
layout_analyzer = LayoutAnalyzer()
semantic_checker = SemanticChecker()

# 自定义异常处理，符合规范要求的HTTP状态码
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "message": "Parameters validation failed"}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Internal error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "message": "Internal server error"}
    )

async def save_result_to_db(request: AuditRequest, response: AuditResponse, status: TaskStatus, error_msg: str = None):
    """
    异步写入 review_tasks 表，符合开发规范的数据持久化要求
    """
    try:
        async for session in db_manager.get_session():
            task = ReviewTask(
                task_id=request.request_id,
                paper_id=request.metadata.paper_id,
                chunk_id=request.metadata.chunk_id,
                agent_name=AGENT_NAME,
                agent_version=AGENT_VERSION,
                status=status,
                score=response.result.score if response else 0,
                audit_level=response.result.audit_level.value if response else None,
                result_json=response.result.model_dump(mode='json') if response else None,
                error_msg=error_msg,
                usage_tokens=response.usage.tokens if response else 0,
                latency_ms=response.usage.latency_ms if response else 0
            )
            session.add(task)
            await session.commit()
            logger.info(f"Task {request.request_id} saved to DB.")
            break
    except Exception as e:
        logger.error(f"Failed to save task to DB: {e}")

@app.post("/audit", response_model=AuditResponse, tags=["Audit"], summary="执行论文格式审计")
async def audit_paper(request: AuditRequest):
    """
    接收论文切片，执行视觉与语义层面的格式审计，返回符合系统协议的JSON结果。
    Ref: 开发规范 - 四、API交互规范
    """
    start_time = time.time()
    logger.info(f"Received audit request: {request.request_id} for paper {request.metadata.paper_id}")
    
    try:
        # 1. 视觉/布局分析
        logger.info("Starting layout analysis...")
        try:
            layout_data = await asyncio.wait_for(layout_analyzer.analyze(request.payload.content), timeout=5)
        except asyncio.TimeoutError:
            logger.error("Layout analysis timeout")
            layout_data = {
                "elements": [],
                "layout_result": {"layout_issues": []},
                "parse_errors": [{"error_type": "layout_timeout", "message": "layout analysis timeout"}],
                "parse_report": {},
            }
        
        # 2. 语义校验
        logger.info("Starting semantic check...")
        semantic_result = await semantic_checker.check(request.payload.content, layout_data)
        
        # 3. 构造返回结果
        score = semantic_result.get("score", 100)
        layout_issues = layout_data.get("layout_result", {}).get("layout_issues", [])
        issues = layout_issues + semantic_result.get("semantic_issues", [])

        # 评分与评级逻辑
        audit_level = AuditLevel.INFO
        if score < 60:
            audit_level = AuditLevel.CRITICAL
        elif score < 80:
            audit_level = AuditLevel.WARNING
            
        comment = "格式审计完成。"
        suggestion = "请检查文中标记的格式问题。"
        if issues:
            comment = f"发现 {len(issues)} 个格式问题。"
            suggestion = "建议根据详细报告进行修改。"
            
        # 使用规范定义的专属Tags
        tags = [AuditTag.CITATION_INCONSISTENCY.value, AuditTag.LABEL_MISSING.value]
        
        # 计算耗时
        latency_ms = int((time.time() - start_time) * 1000)
        
        # 估算Token消耗
        tokens = len(request.payload.content) // 4 

        response = AuditResponse(
            request_id=request.request_id,
            agent_info=AgentInfo(name=AGENT_NAME, version=AGENT_VERSION),
            result=AuditResult(
                score=score,
                audit_level=audit_level,
                comment=comment,
                suggestion=suggestion,
                tags=tags
            ),
            usage=ResourceUsage(
                tokens=tokens,
                latency_ms=latency_ms
            )
        )
        
        # 4. 异步写入数据库 (Fire-and-forget or await depending on requirement)
        # 规范要求"实时写入"，这里使用 await 确保数据落库
        await save_result_to_db(request, response, TaskStatus.SUCCESS)
        
        return response
        
    except Exception as e:
        # 记录失败状态
        await save_result_to_db(request, None, TaskStatus.FAILED, error_msg=str(e))
        raise e

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "Standardization Auditor Agent is running",
        "docs": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
