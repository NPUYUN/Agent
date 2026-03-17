# 寒假专业实践项目 -- 多智能体构建 (Group 2)

本小组（第二组）主要负责**格式审计组（Standardization Auditor Agent）**的开发。核心任务是利用PDF解析技术提取元素坐标，结合计算机视觉（CV）分析PDF布局，核查图表/公式位置，将视觉排版转化为文本逻辑规则，并进行语义层面的格式校验。

## 项目结构

系统基于 **FastAPI (异步)** 构建，严格遵循**四层闭环数据流向**与**三步闭环逻辑**。

```
Standardization_Auditor_Agent/
├── core/                       # 核心业务逻辑
│   ├── database.py             # 数据库连接管理 (Async SQLAlchemy, ReviewTask模型)
│   ├── rule_engine.py          # 动态规则加载与管理
│   ├── layout_analysis.py      # 视觉/布局分析主入口 (CV Layer)
│   ├── layout_zones.py         # 区域划分逻辑 (6大区域)
│   ├── layout_rules.py         # 布局校验规则
│   ├── layout_payload.py       # 数据载荷构建
│   ├── layout_frontend_adapter.py # 前端适配器 (锚点转换)
│   ├── semantic_check.py       # 语义规则校验模块 (Semantic Layer)
│   │   ├── TypoChecker         # 错别字红线判定 (>10 Warning)
│   │   ├── TerminologyChecker  # 术语一致性校验
│   │   ├── PunctuationChecker  # 标点符号校验
│   │   ├── CitationChecker     # 引用格式语义校验
│   │   └── SemanticChecker     # 语义校验入口
│   └── llm_client.py           # 统一 LLM 客户端 (支持 Gemini/Qwen/DeepSeek/Mock)
├── utils/                      # 通用工具库
│   └── logger.py               # 标准化日志模块
├── tests/                      # unittest 测试用例
├── scripts/                    # 运维脚本
│   └── seed_rules.py           # 规则库入库脚本
├── config.py                   # 全局配置 (Prompt, Version, Tags)
├── rules.yaml                  # 语义校验规则配置文件 (动态可调)
├── models.py                   # Pydantic 数据模型 (严格遵循 API 协议)
├── main.py                     # FastAPI 应用入口 (含生命周期与DB写入)
├── requirements.txt            # 项目依赖 (精准版本)
└── Dockerfile                  # 容器化构建文件
```

测试操作指南见项目根目录的 `测试说明.md`。

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
- **LLM Integration**: 集成 `Gemini` / `Qwen` (Compatible Mode) 辅助长文档扫描。

### 3. 数据测试/标注 (Data Support) - 1人
- **样本库搭建**: 收集≥200份样本（规范/单一问题/混合问题），覆盖图表/公式/标题/错别字/术语/标点/引用等维度，并按问题类型分类管理。
- **标注规范与数据集**: 制定标准化格式问题标注手册，约定“问题类型/页码/坐标/证据文本/风险等级/修正建议”的记录方式，并将标注结果沉淀为可直接加载的测试数据集（Excel + JSON）。
- **测试用例与回归**: 设计并维护针对 CV/布局与语义判定模块的单元测试、集成测试、场景化测试用例，优先通过 `tests/` 目录下的单元测试（`python -m unittest discover -s tests`）与端到端脚本（`audit_client.py`）完成回归测试，确保不同版本之间结果可比对、可追溯。
- **一致性核查**: 对接 Orchestrator 与前端，核查审计结果 JSON 的完整性（是否符合开发规范中的 API 协议）与数据库写入字段的完整性，确保 JSON 结构、数据库字段、前端展示三者一致；同时检查锚点定位与导师复核流程是否正常。

## 核心交互流程

1.  **请求接收**: `POST /audit` 接收 Orchestrator 发送的论文切片。
2.  **视觉分析**: `LayoutAnalyzer` 解析 PDF 结构，校验视觉格式。
3.  **语义校验**: `SemanticChecker` 结合视觉数据，执行语义规则检查。
4.  **结果融合**: 合并 CV 与 Semantic 问题的列表，去重。
5.  **数据持久化**: 异步写入 `review_tasks` 数据库表 (PostgreSQL)。
6.  **响应返回**: 返回符合 API 协议的 JSON 结果。

> 数据测试/标注 岗需基于上述流程，持续维护与扩展配套测试数据与测试用例，保证每次修改都能快速通过自动化测试完成验证。

## 快速开始

### 1. 环境准备

确保已安装 Python 3.10.x。

### 2. 安装依赖

```bash
cd Standardization_Auditor_Agent
pip install -r requirements.txt
```

### 3. 配置环境变量

支持 **Gemini** (Google)、**Qwen** (DashScope/Aliyun)、**DeepSeek** (OpenAI Compatible) 以及 **Mock** 多模型切换。推荐使用 `.env` 文件或系统环境变量进行配置。

1. 推荐在 Windows PowerShell 下使用 `Standardization_Auditor_Agent/set_env.local.ps1` 写入临时环境变量（该文件默认被忽略，不应提交真实 Key/密码）。

2. 或者在 `Standardization_Auditor_Agent` 目录下创建/编辑 `.env`（不要提交真实 Key/密码；本仓库默认忽略所有 `.env*` 文件）：

```ini
# LLM Configuration
# Options: gemini, qwen, deepseek, mock
LLM_PROVIDER=deepseek

# DeepSeek API Configuration
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_MODEL_NAME=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Qwen API Configuration (Optional)
QWEN_API_KEY=your_qwen_api_key
QWEN_MODEL_NAME=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Timeout settings
LLM_TIMEOUT_SEC=60
LAYOUT_ANALYSIS_TIMEOUT=300

# Database Configuration
# 内网库：需要连接学校 VPN 才能访问
# DB_HOST=10.13.1.26
# DB_PORT=5432
# DB_NAME=postgres
#
# 本机/容器库（示例）：按需覆盖
# DB_HOST=localhost
# DB_PORT=5433
# DB_NAME=agent_db
# DB_USER=postgres
# DB_PASSWORD=your_password
```

### 4. 初始化数据库

```bash
python ensure_db.py
```

说明：
- 若连接内网数据库且账号为“只允许使用现有表、禁止建表”，请不要用该账号执行 `ensure_db.py` / `seed_rules.py` 等可能涉及 DDL 的脚本；这类脚本应使用具备 DDL 权限的管理员账号执行。

### 5. 运行审计

#### 方式一：CLI 命令行直接审计 PDF

无需启动服务器，直接对本地 PDF 文件进行审计并生成 Markdown 报告。

```bash
cd Standardization_Auditor_Agent
python main.py --pdf "path/to/your/paper.pdf"
```

**输出结果**：
默认会在当前目录下的 `report` 文件夹生成两份报告：
- `*_score_report.md`: 评分报告（总分、评级、各类问题统计）。
- `*_deduction_details.md`: 扣分细则（包含 CV 视觉布局分析 和 LLM 语义内容分析的详细问题列表）。

#### LLM 分块策略（语义审计）

当启用 LLM 语义扫描时，会按段落进行分块，默认分块上限 15000 字符、重叠 500 字符。分块策略保证：
- 段落不会被拆分到两个分块中（除非单段落本身超过上限）。
- 超长段落会单独分块，并在段落内部按句子/分隔符切分，避免产生过小分块。

#### 方式二：启动 API 服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
服务默认运行在 `http://0.0.0.0:8000`。

### 6. 运行测试与示例

详细测试步骤请参考 [测试说明文档](测试说明.md)。

- **单元测试 (unittest)**  
  在 `Standardization_Auditor_Agent` 目录下运行：
  ```bash
  python -m unittest discover -s tests
  ```
  若 `tests/` 目录为空或未包含可运行用例，建议优先使用下方端到端示例与手动接口验证完成回归检查。

- **端到端示例（PDF → 审计结果）**  
  在 `Standardization_Auditor_Agent` 目录下运行：
  ```bash
  python audit_client.py
  ```
  - 若未指定文件，将自动生成一份包含典型格式问题的示例 PDF (`sample_audit.pdf`)，并调用已启动的 Agent 服务；
  - 终端会打印评分 (`score`)、风险等级 (`audit_level`)、问题标签 (`tags`) 以及完整 JSON 响应，便于人工核对与后续标注。

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
    "content": "Base64 PDF 或 Markdown 文本...",
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
- **核心库**: PyMuPDF, OpenCV, google-genai, openai, SQLAlchemy (Async)
- **数据持久化**: 结果实时写入 PostgreSQL (`review_tasks` 表)
