import os
import sys
import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    if not os.getenv("LLM_PROVIDER"):
        os.environ["LLM_PROVIDER"] = "deepseek"

from models import AuditRequest, AuditResponse, AgentInfo, AuditResult, ResourceUsage, AuditLevel, IssueDetail
from core.layout_analysis import LayoutAnalyzer
from api.layout_routes import router as layout_router
from core.semantic_check import SemanticChecker
from core.pdf_utils import open_pdf
from core.database import db_manager, ReviewTask, TaskStatus, PaperSection
from core.rule_engine import RuleEngine
from utils.logger import setup_logger
from config import AGENT_NAME, AGENT_VERSION, AuditTag, LAYOUT_ANALYSIS_TIMEOUT, LLM_PROVIDER, DATABASE_URL
from sqlalchemy import select

# 初始化日志
logger = setup_logger(AGENT_NAME)

# 初始化规则引擎
rule_engine = RuleEngine()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：连接数据库
    logger.info("==================================================")
    logger.info(f"   {AGENT_NAME} {AGENT_VERSION} Starting up...")
    logger.info("==================================================")
    logger.info(f"LLM Provider: {LLM_PROVIDER}")
    logger.info(f"DB Connection: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'Hidden'}")
    logger.info(f"Layout Timeout: {LAYOUT_ANALYSIS_TIMEOUT}s")
    
    logger.info("Starting up: Connecting to database...")
    # await db_manager.engine.connect() # SQLAlchemy async engine is lazy
    
    # Load rules from DB (Task A: Dynamic Rule Loading)
    loaded = await rule_engine.load_rules_from_db()
    if loaded:
        logger.info("Rules loaded from DB successfully.")
    else:
        logger.warning("Rules not loaded from DB; using YAML rules.")

    # Inject rules into core components
    layout_analyzer.update_rules(rule_engine.rules)
    semantic_checker.update_rules(rule_engine.rules)

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

def _collect_tags(issues):
    tag_set = set()
    for issue in issues:
        issue_type = ""
        if isinstance(issue, dict):
            issue_type = issue.get("issue_type", "") or ""
        else:
            issue_type = getattr(issue, "issue_type", "") or ""
        if not issue_type:
            continue
        if "Citation" in issue_type:
            tag_set.add(AuditTag.CITATION_INCONSISTENCY.value)
        if issue_type == "Label_Missing":
            tag_set.add(AuditTag.LABEL_MISSING.value)
        if issue_type == "Hierarchy_Fault":
            tag_set.add(AuditTag.HIERARCHY_FAULT.value)
        if "Punctuation" in issue_type:
            tag_set.add(AuditTag.PUNCTUATION_ERROR.value)
    return list(tag_set)

async def save_result_to_db(request: AuditRequest, response: AuditResponse | None, status: TaskStatus, error_msg: str | None = None):
    """
    异步写入 review_tasks 表，符合开发规范的数据持久化要求
    """
    try:
        async for session in db_manager.get_session():
            stmt = (
                select(ReviewTask)
                .where(
                    ReviewTask.task_id == request.request_id,
                    ReviewTask.paper_id == request.metadata.paper_id,
                    ReviewTask.chunk_id == request.metadata.chunk_id,
                    ReviewTask.agent_name == AGENT_NAME,
                )
                .order_by(ReviewTask.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

            if task is None:
                task = ReviewTask(
                    task_id=request.request_id,
                    paper_id=request.metadata.paper_id,
                    chunk_id=request.metadata.chunk_id,
                    agent_name=AGENT_NAME,
                    agent_version=AGENT_VERSION,
                )
                session.add(task)

            task.agent_version = AGENT_VERSION
            task.status = status
            task.score = response.result.score if response else None
            task.audit_level = response.result.audit_level.value if response else None
            task.result_json = response.model_dump(mode="json") if response else None
            task.error_msg = error_msg
            task.usage_tokens = response.usage.tokens if response else 0
            task.latency_ms = response.usage.latency_ms if response else 0
            await session.commit()
            logger.info(f"Task {request.request_id} saved to DB (status={status}).")
            break
    except Exception as e:
        logger.error(f"Failed to save task to DB: {type(e).__name__}: {e!r}")

@app.post("/audit", response_model=AuditResponse, tags=["Audit"], summary="执行论文格式审计")
async def audit_paper(request: AuditRequest):
    """
    接收论文切片，执行视觉与语义层面的格式审计，返回符合系统协议的JSON结果。
    Ref: 开发规范 - 四、API交互规范
    """
    start_time = time.time()
    logger.info(f"Received audit request: {request.request_id} for paper {request.metadata.paper_id}")
    
    try:
        await save_result_to_db(request, None, TaskStatus.RUNNING)

        # Check if content is provided, if not fetch from DB
        content = request.payload.content
        if not content:
            logger.info(f"Content missing in payload. Fetching from DB for paper {request.metadata.paper_id}, chunk {request.metadata.chunk_id}")
            try:
                # Use a new session to fetch content
                async for session in db_manager.get_session():
                    stmt = select(PaperSection).where(
                        PaperSection.paper_id == request.metadata.paper_id,
                        PaperSection.chunk_id == request.metadata.chunk_id
                    )
                    result = await session.execute(stmt)
                    section = result.scalar_one_or_none()
                    if section:
                        content = section.content
                    break # Close session
            except Exception as e:
                logger.error(f"Failed to fetch content from DB: {type(e).__name__}: {e!r}")
            
            if not content:
                raise HTTPException(status_code=400, detail=f"Missing payload.content and no matching content found in DB for paper {request.metadata.paper_id} chunk {request.metadata.chunk_id}")
            
            # Update request payload with fetched content
            request.payload.content = content

        # 1. 视觉/布局分析
        logger.info("Starting layout analysis...")
        try:
            layout_data = await asyncio.wait_for(layout_analyzer.analyze(request.payload.content), timeout=LAYOUT_ANALYSIS_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"Layout analysis timeout (>{LAYOUT_ANALYSIS_TIMEOUT}s)")
            page_count = None
            try:
                doc = open_pdf(request.payload.content)
                page_count = len(doc)
                doc.close()
            except Exception:
                page_count = None
            layout_data = {
                "elements": [],
                "layout_result": {"layout_issues": []},
                "parse_errors": [{"error_type": "layout_timeout", "message": "layout analysis timeout"}],
                "parse_report": {"page_count": page_count} if page_count else {},
            }
        
        # 2. 语义校验
        logger.info("Starting semantic check...")
        semantic_result = await semantic_checker.check(request.payload.content, layout_data)
        
        # 3. 构造返回结果
        layout_issues = layout_data.get("layout_result", {}).get("layout_issues", [])
        issues = layout_issues + semantic_result.get("semantic_issues", [])
        score = semantic_checker._calculate_score(issues)

        # 转换为 IssueDetail 对象列表
        issue_details = []
        for i in issues:
            try:
                if isinstance(i, dict):
                    issue_details.append(IssueDetail(**i))
                elif hasattr(i, 'model_dump'):
                    issue_details.append(IssueDetail(**i.model_dump()))
            except Exception as e:
                logger.warning(f"Failed to convert issue to IssueDetail: {e}, issue: {i}")

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

        rag_comment, rag_suggestion = await semantic_checker.generate_expert_commentary(
            request.payload.content, issues
        )
        if rag_comment and rag_suggestion:
            comment = rag_comment
            suggestion = rag_suggestion
            
        tags = _collect_tags(issues) if issues else []
        
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
                tags=tags,
                issues=issue_details
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

@app.get("/rules")
async def get_rules():
    """获取当前加载的动态规则 (用于测试验证)"""
    return rule_engine.rules

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/", response_class=HTMLResponse)
async def root():
    html_content = f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>{AGENT_NAME}</title>
            <style>
                body {{ font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
                .status {{ padding: 10px; border-radius: 5px; background: #e0f7fa; }}
                .config {{ background: #f5f5f5; padding: 10px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>{AGENT_NAME} ({AGENT_VERSION})</h1>
            <div class="status">
                <p>Status: <strong>Running</strong></p>
                <p>Docs: <a href="/docs">/docs</a> | Health: <a href="/health">/health</a> | Rules: <a href="/rules">/rules</a></p>
            </div>
            <h3>Current Configuration</h3>
            <div class="config">
                <pre>
LLM_PROVIDER: {LLM_PROVIDER}
DB_CONNECTION: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'Hidden'}
LAYOUT_TIMEOUT: {LAYOUT_ANALYSIS_TIMEOUT}s
                </pre>
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Standardization Auditor Agent\n\n"
                    "用法：\n"
                    "- 不带参数：启动 FastAPI 服务\n"
                    "- 带 --pdf：直接审计本地 PDF 并生成报告",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--pdf", help="本地 PDF 文件路径（启用 CLI 审计模式）")
    parser.add_argument(
        "--pages",
        help="仅审计指定页码（可用逗号分隔与范围）：例如 1,2,10-12。默认：审计全部页",
    )
    parser.add_argument(
        "--output",
        help="输出路径：目录或 .json 文件路径。\n"
             "- 目录：Markdown 报告输出到该目录\n"
             "- .json：除 Markdown 外，额外生成该 JSON 汇总文件\n"
             "默认：./report",
    )
    args = parser.parse_args()

    if args.pdf:
        import fitz
        import json
        import numpy as np
        import math
        import re
        from datetime import datetime

        class NpEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                if isinstance(obj, np.floating):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)

        def _parse_pages_spec(spec: str | None) -> list[int] | None:
            if not spec:
                return None
            raw = str(spec).strip()
            if not raw:
                return None
            out: set[int] = set()
            for part in re.split(r"[,\s]+", raw):
                p = part.strip()
                if not p:
                    continue
                if "-" in p:
                    a, b = (x.strip() for x in p.split("-", 1))
                    if not a.isdigit() or not b.isdigit():
                        continue
                    start, end = int(a), int(b)
                    if start <= 0 or end <= 0:
                        continue
                    if end < start:
                        start, end = end, start
                    for n in range(start, end + 1):
                        out.add(n)
                    continue
                if p.isdigit():
                    n = int(p)
                    if n > 0:
                        out.add(n)
            if not out:
                return None
            return sorted(out)

        async def run_audit():
            # Load rules
            await rule_engine.load_rules_from_db()
            
            # Update components
            layout_analyzer.update_rules(rule_engine.rules)
            semantic_checker.update_rules(rule_engine.rules)

            pdf_path = args.pdf
            if not os.path.exists(pdf_path):
                print(f"Error: File not found: {pdf_path}")
                return

            print(f"Starting audit for: {pdf_path}")
            selected_pages = _parse_pages_spec(args.pages)
            selected_set = set(selected_pages or [])
            
            # 1. Extract text
            doc = fitz.open(pdf_path)
            text_content = ""
            for idx, page in enumerate(doc):
                page_num = idx + 1
                if selected_pages and page_num not in selected_set:
                    continue
                text_content += page.get_text()
            
            # 2. Layout Analysis
            print("Running Layout Analysis...")
            try:
                layout_input = {"pdf_path": pdf_path, "pages": selected_pages} if selected_pages else pdf_path
                layout_data = await asyncio.wait_for(layout_analyzer.analyze(layout_input), timeout=LAYOUT_ANALYSIS_TIMEOUT)
            except asyncio.TimeoutError:
                layout_data = {
                    "elements": [],
                    "layout_result": {"layout_issues": []},
                    "parse_errors": [{"error_type": "layout_timeout", "message": "layout analysis timeout"}],
                    "parse_report": {"page_count": len(doc)} if doc else {},
                }
            except Exception as e:
                layout_data = {
                    "elements": [],
                    "layout_result": {"layout_issues": []},
                    "parse_errors": [{"error_type": "layout_error", "message": str(e)}],
                    "parse_report": {"page_count": len(doc)} if doc else {},
                }
            
            # 3. Semantic Check
            provider = getattr(getattr(semantic_checker, "llm_client", None), "provider", "none")
            print(f"Running Semantic Check (powered by {provider} API)...")
            semantic_result = await semantic_checker.check(text_content, layout_data)
            
            # 4. Merge Issues
            layout_issues = layout_data.get("layout_result", {}).get("layout_issues", [])
            semantic_issues = semantic_result.get("semantic_issues", [])
            all_issues = layout_issues + semantic_issues
            
            # 5. Calculate Score
            score = semantic_checker._calculate_score(all_issues)
            
            # Count issues by severity
            counts = {"Critical": 0, "Warning": 0, "Info": 0}
            for issue in all_issues:
                level = issue.get("severity") or issue.get("level") or "Info"
                if level not in counts: level = "Info"
                counts[level] += 1
            
            critical = counts["Critical"]
            warning = counts["Warning"]
            info = counts["Info"]

            # Determine Audit Level
            audit_level = "PASS"
            if score < 60:
                audit_level = "CRITICAL"
            elif score < 80:
                audit_level = "WARNING"
            
            # 6. Console Summary
            print("\n" + "="*60)
            print(f"AUDIT REPORT: {os.path.basename(pdf_path)}")
            print(f"SCORE: {score}/100 ({audit_level})")
            print(f"TOTAL ISSUES: {len(all_issues)}")
            print("="*60)
            
            issues_by_type = {}
            for issue in all_issues:
                t = issue.get("issue_type", "Other")
                if t not in issues_by_type:
                    issues_by_type[t] = []
                issues_by_type[t].append(issue)
            
            for t, issues in issues_by_type.items():
                print(f"\n[ {t} ] - {len(issues)} issues")
                for i, issue in enumerate(issues[:3]): # Show top 3 in console
                    msg = issue.get("message", "")
                    pg = issue.get("page_num", "?")
                    print(f"  - (Page {pg}) {msg}")
                if len(issues) > 3:
                    print(f"  ... and {len(issues)-3} more")

            # 7. Generate Markdown Reports
            # Determine output directory
            # Default to "report" folder in the current working directory
            output_dir = os.path.join(os.getcwd(), "report")
            
            if args.output:
                # If extension exists, treat as file path and get its directory
                if os.path.splitext(args.output)[1]:
                    output_dir = os.path.dirname(args.output) or "."
                else:
                    # Otherwise treat as directory
                    output_dir = args.output
            
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)

            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            score_report_path = os.path.join(output_dir, f"{base_name}_score_report.md")
            deduction_report_path = os.path.join(output_dir, f"{base_name}_deduction_details.md")

            # Generate Score Report
            with open(score_report_path, "w", encoding="utf-8") as f:
                f.write(f"# 论文格式审计评分报告\n\n")
                f.write(f"**文件名**: {os.path.basename(pdf_path)}\n\n")
                f.write(f"**审计时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"## 审计结果\n")
                f.write(f"- **总分**: {score}/100\n")
                f.write(f"- **评级**: {audit_level}\n")
                f.write(f"- **问题总数**: {len(all_issues)}\n\n")
                
                f.write("## 问题统计\n")
                f.write(f"- **Critical (严重)**: {critical}\n")
                f.write(f"- **Warning (警告)**: {warning}\n")
                f.write(f"- **Info (提示)**: {info}\n\n")
                
                f.write("## 评分说明\n")
                f.write("本系统采用非线性扣分机制，避免单一类问题导致分数过低：\n")
                scoring = getattr(semantic_checker, "rules", {}) or {}
                scoring_cfg = scoring.get("scoring", {}) if isinstance(scoring, dict) else {}
                critical_w = float(scoring_cfg.get("critical_weight", 5.0) or 5.0)
                warning_w = float(scoring_cfg.get("warning_weight", 2.0) or 2.0)
                info_w = float(scoring_cfg.get("info_weight", 0.5) or 0.5)
                f.write(f"- **Critical**: 权重 {critical_w:g} (线性扣分)\n")
                f.write(f"- **Warning**: 权重 {warning_w:g} (平方根非线性扣分)\n")
                f.write(f"- **Info**: 权重 {info_w:g} (平方根非线性扣分)\n\n")
                
                deduction = critical_w * critical + warning_w * math.sqrt(warning) + info_w * math.sqrt(info)
                f.write(f"**总扣分计算**: `{critical_w:g} * {critical} + {warning_w:g} * sqrt({warning}) + {info_w:g} * sqrt({info})` ≈ `{deduction:.2f}`\n")
                f.write(f"**最终得分**: `100 - {int(round(deduction))}` = `{score}`\n")

            # Generate Deduction Details Report
            with open(deduction_report_path, "w", encoding="utf-8") as f:
                f.write(f"# 论文格式审计扣分细则\n\n")
                f.write(f"**文件名**: {os.path.basename(pdf_path)}\n")
                f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                def _norm_text(value: object) -> str:
                    s = "" if value is None else str(value)
                    s = re.sub(r"\s+", " ", s).strip()
                    return s

                def _fmt_bbox(bbox: object) -> str:
                    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                        try:
                            x0, y0, x1, y1 = [float(x) for x in bbox]
                            return f"[{x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f}]"
                        except Exception:
                            return _norm_text(bbox)
                    return ""

                def _write_issue_detail(issue: dict):
                    evidence = issue.get("evidence")
                    bbox = issue.get("bbox")
                    location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
                    if not bbox and isinstance(location, dict):
                        bbox = location.get("bbox")
                    bbox_str = _fmt_bbox(bbox)
                    if bbox_str:
                        f.write(f"- **BBox**: {bbox_str}\n")
                    if evidence:
                        ev = _norm_text(evidence)
                        if ev:
                            if len(ev) <= 120:
                                f.write(f"- **证据**: `{ev}`\n")
                            else:
                                f.write(f"- **证据**:\n\n```\n{ev}\n```\n")
                
                if not all_issues:
                    f.write("恭喜！未发现明显的格式问题。\n")
                else:
                    # 1. Layout Analysis (CV)
                    f.write("## 1. 视觉布局分析 (CV Layout Analysis)\n")
                    if not layout_issues:
                        f.write("未发现布局问题。\n\n")
                    else:
                        layout_by_type = {}
                        for issue in layout_issues:
                            t = issue.get("issue_type", "Other")
                            if t not in layout_by_type: layout_by_type[t] = []
                            layout_by_type[t].append(issue)
                        
                        for t, issues in layout_by_type.items():
                            f.write(f"### {t} ({len(issues)} 个问题)\n")
                            for i, issue in enumerate(issues):
                                msg = issue.get("message", "无描述")
                                pg = issue.get("page_num", "?")
                                severity = issue.get("severity", "Info")
                                suggestion = issue.get("suggestion", "")
                                
                                f.write(f"#### {i+1}. [Page {pg}] {msg}\n")
                                f.write(f"- **严重程度**: {severity}\n")
                                if isinstance(issue, dict):
                                    _write_issue_detail(issue)
                                if suggestion:
                                    f.write(f"- **修改建议**: {suggestion}\n")
                                f.write("\n")
                    
                    f.write("\n")

                    # 2. Semantic Analysis (LLM)
                    f.write("## 2. 语义内容分析 (LLM Semantic Analysis)\n")
                    if not semantic_issues:
                        f.write("未发现语义问题。\n\n")
                    else:
                        semantic_by_type = {}
                        for issue in semantic_issues:
                            t = issue.get("issue_type", "Other")
                            if t not in semantic_by_type: semantic_by_type[t] = []
                            semantic_by_type[t].append(issue)
                        
                        for t, issues in semantic_by_type.items():
                            f.write(f"### {t} ({len(issues)} 个问题)\n")
                            for i, issue in enumerate(issues):
                                msg = issue.get("message", "无描述")
                                pg = issue.get("page_num", "?")
                                severity = issue.get("severity", "Info")
                                suggestion = issue.get("suggestion", "")
                                
                                f.write(f"#### {i+1}. [Page {pg}] {msg}\n")
                                f.write(f"- **严重程度**: {severity}\n")
                                if isinstance(issue, dict):
                                    _write_issue_detail(issue)
                                if suggestion:
                                    f.write(f"- **修改建议**: {suggestion}\n")
                                f.write("\n")

            print(f"\nReports generated successfully:")
            print(f"1. Score Report: {score_report_path}")
            print(f"2. Deduction Details: {deduction_report_path}")

            if args.output and args.output.endswith('.json'):
                report = {
                    "file": pdf_path,
                    "score": score,
                    "issues": all_issues
                }
                with open(args.output, "w", encoding="utf-8") as f:
                    json.dump(report, f, cls=NpEncoder, ensure_ascii=False, indent=2)
                print(f"3. JSON Report: {args.output}")

        asyncio.run(run_audit())
        
    else:
        uvicorn.run(app, host="127.0.0.1", port=8000)
