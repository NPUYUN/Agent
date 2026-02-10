# 寒假专业实践项目 -- 多智能体构建 (Group 2)

本小组（第二组）主要负责**格式审计组（Standardization Auditor Agent）**的开发。核心任务是利用PDF解析技术提取元素坐标，结合计算机视觉（CV）分析PDF布局，核查图表/公式位置，将视觉排版转化为文本逻辑规则，并进行语义层面的格式校验。

## 项目结构

系统基于 **FastAPI (异步)** 构建，严格遵循**四层闭环数据流向**与**三步闭环逻辑**。

```
Standardization_Auditor_Agent/
├── core/                       # 核心业务逻辑
│   ├── database.py             # 数据库连接管理 (Async SQLAlchemy, ReviewTask模型)
│   ├── rule_engine.py          # 动态规则加载与管理
│   ├── layout_analysis.py      # 视觉/布局分析模块 (CV Layer)
│   │   ├── PDFParser           # PDF解析与元素提取 (6大区域划分)
│   │   ├── VisualValidator     # CV视觉校验 (图表/公式/标题/引用)
│   │   └── AnchorGenerator     # 前端锚点生成 (精准BBox)
│   ├── semantic_check.py       # 语义规则校验模块 (Semantic Layer)
│   │   ├── TypoChecker         # 错别字红线判定 (>10 Warning)
│   │   ├── TerminologyChecker  # 术语一致性校验
│   │   ├── PunctuationChecker  # 标点符号校验
│   │   ├── CitationChecker     # 引用格式语义校验
│   │   └── SemanticChecker     # 语义校验入口
│   └── llm_client.py           # Gemini 1.5 Flash 客户端 (长文档扫描)
├── utils/                      # 通用工具库
│   └── logger.py               # 标准化日志模块
├── tests/                      # 测试用例
│   └── test_api.py             # API 接口测试
├── config.py                   # 全局配置 (Prompt, Version, Tags)
├── rules.yaml                  # 语义校验规则配置文件 (动态可调)
├── models.py                   # Pydantic 数据模型 (严格遵循 API 协议)
├── main.py                     # FastAPI 应用入口 (含生命周期与DB写入)
├── requirements.txt            # 项目依赖 (精准版本)
└── Dockerfile                  # 容器化构建文件
```

## 核心任务与分工 (基于分工明细)

本项目严格按照《分工明细》划分为三大核心任务：

### 1. CV/布局开发 (Visual Layer) - 2人
- **PDFParser**: 基于 `PyMuPDF` 实现 PDF 页面解析，自动划分为**正文/图表/公式/标题/参考文献/引用标注** 6大核心区域。
- **VisualValidator**: 基于 `OpenCV` 进行视觉特征分析：
    - **图表**: 标号关联、标题位置（图下/表上）。
    - **公式**: 编号右对齐、编号与引用匹配。
    - **标题**: 层级视觉特征（字体/字号）、序号跳级检测。
- **AnchorGenerator**: 为每个问题生成精准的坐标锚点（页码 + BBox），支持前端点击跳转高亮。

### 2. 语义判定 (Semantic Layer) - 1人
- **TypoChecker**: 错别字红线判定（全文>10个 Warning，关键术语错字 Critical）。
- **TerminologyChecker**: 术语一致性检查（如 "Deep Learning" 写法统一）。
- **PunctuationChecker**: 杜绝中英文标点混用及位置错误。
- **CitationChecker**: 引用风格（IEEE/APA）一致性及与参考文献的语义匹配。
- **LLM Integration**: 集成 `Gemini 1.5 Flash` 辅助长文档扫描。

### 3. 数据测试/标注 (Data Support) - 1人
- **样本库搭建**: 收集≥200份样本（规范/单一问题/混合问题），覆盖所有审计维度。
- **标注规范**: 制定标准化格式问题标注手册，确保 CV 和 语义 模块的测试基准。
- **一致性核查**: 对接 Orchestrator，核查审计结果 JSON 的完整性与准确性，确保无漏检/误检。

## 核心交互流程

1.  **请求接收**: `POST /audit` 接收 Orchestrator 发送的论文切片。
2.  **视觉分析**: `LayoutAnalyzer` 解析 PDF 结构，校验视觉格式。
3.  **语义校验**: `SemanticChecker` 结合视觉数据，执行语义规则检查。
4.  **结果融合**: 合并 CV 与 Semantic 问题的列表，去重。
5.  **数据持久化**: 异步写入 `review_tasks` 数据库表 (PostgreSQL)。
6.  **响应返回**: 返回符合 API 协议的 JSON 结果。

## 快速开始

### 1. 环境准备

确保已安装 Python 3.10.x。

### 2. 安装依赖

```bash
cd Standardization_Auditor_Agent
pip install -r requirements.txt
```

### 3. 配置环境变量

如需使用 Gemini 模型及数据库连接：

**Windows (PowerShell):**
```powershell
$env:GOOGLE_API_KEY="your_api_key"
$env:DATABASE_URL="postgresql+asyncpg://user:pass@localhost/dbname"
```

### 4. 运行 Agent

```bash
python main.py
```
服务默认运行在 `http://0.0.0.0:8000`。

## API 接口

遵循系统统一的异步交互协议。

### 审计接口 `POST /audit`

**请求示例:**
```json
{
  "request_id": "req_20231027_001",
  "metadata": {
    "paper_id": "uuid-string",
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
```

**响应示例:**
```json
{
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
```

## 开发规范

- **编程语言**: Python 3.10.x
- **Web框架**: FastAPI (必须支持 async)
- **数据校验**: Pydantic V2 (强制校验)
- **核心库**: PyMuPDF, OpenCV, Google Generative AI, SQLAlchemy (Async)
- **数据持久化**: 结果实时写入 PostgreSQL (`review_tasks` 表)
