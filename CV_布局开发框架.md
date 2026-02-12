# CV/布局开发模块框架（基于分工明细与项目计划 + 现有项目）

## 1. 背景与目标
CV/布局开发模块负责将论文的视觉排版结构转化为可审计的结构化数据，输出标准化视觉元素与视觉审计问题，并为前端提供精准锚点坐标，支撑“点击评语定位原文”的交互能力。模块需与中枢组Orchestrator、语义判定模块、前端渲染协同工作，遵循无状态、异步、严格Schema的工程规范。

## 2. 与现有项目结构对齐
现有代码已提供视觉层骨架，核心入口与类定义在：
- `Standardization_Auditor_Agent/core/layout_analysis.py`
  - `PDFParser`：PDF解析与基础视觉元素提取（阶段2）
  - `VisualValidator`：视觉校验逻辑（阶段3）
  - `AnchorGenerator`：锚点坐标生成（阶段4）
  - `LayoutAnalyzer`：视觉层总入口，输出 elements + layout_result
- `Standardization_Auditor_Agent/models.py`
  - 定义了全链路审计模型与风险等级
- `Standardization_Auditor_Agent/main.py`
  - FastAPI入口，后续通过审计引擎聚合视觉/语义结果

本框架将严格复用上述骨架，按任务划分逐步补全功能逻辑，而不改变现有模块边界。

## 3. 视觉元素与问题的标准化数据格式
### 3.1 视觉元素 VisualElement（与现有模型对齐）
字段约定：
- `type`: text | image | formula | table | title | reference | citation
- `content`: 文本内容或描述
- `bbox`: [x0, y0, x1, y1]，单位为PDF原坐标
- `page_num`: 页码（从1开始）
- `region`: main | chart | formula | title | reference | citation
- `paper_id`, `chunk_id`: 上游元数据透传，用于联动与定位

### 3.2 视觉问题 Issue（输出至布局结果）
统一字段：
- `issue_type`: Label_Missing | Formula_Misaligned | Hierarchy_Fault | Citation_Visual_Fault 等
- `severity`: Info | Warning | Critical
- `page_num`
- `bbox`
- `evidence`: 原文证据片段
- `message`: 人可读描述

### 3.3 锚点 Anchor（前端联动）
锚点字段：
- `page_num`
- `bbox`
- `highlight`: {x0, y0, x1, y1}（可与bbox一致）
- `anchor_id`: 便于前端定位/去重

## 4. 模块总体流程
```
PDF内容/路径
   │
   ▼
PDFParser.parse
   ├─ 页面读取与基础信息提取
   ├─ 6大区域划分
   └─ 区域级元素精细化提取 → VisualElement[]
   │
   ▼
VisualValidator.validate
   ├─ 图表校验
   ├─ 公式校验
   ├─ 标题层级校验
   └─ 引用标注校验 → issues[]
   │
   ▼
AnchorGenerator.generate_anchors
   └─ issues + bbox → anchors[]
   │
   ▼
LayoutAnalyzer.analyze
   └─ 输出 {elements, layout_result}
```

## 5. PDFParser 设计（阶段2）
### 5.1 页面读取与基础信息提取
使用 PyMuPDF（fitz）读取：
- 页面尺寸、边距
- 文本块与字体信息
- 图片/图表区域坐标

输出基础元数据，用于后续区域划分与视觉校验。

### 5.2 6大区域划分逻辑
区域：正文区、图表区、公式区、标题区、参考文献区、引用标注区。
核心策略：
- 基于页面坐标分区（上/中/下、左/右）
- 结合字体样式（标题常见更大字号或加粗）
- 结合固定特征（“参考文献”标题、图/表/式编号前缀）

### 5.3 视觉元素精细化提取
按区域提取：
| 区域 | 元素 | 关键特征 |
|---|---|---|
| 图表区 | 图/表编号、标题、图像区域 | “图/表X”文本 + 近邻图像bbox |
| 公式区 | 公式编号、公式区域 | 右侧编号对齐 + 公式块 |
| 标题区 | 标题文本、层级特征 | 字体/字号/缩进/提醒行距 |
| 引用标注区 | [1] / (Wang,2023) | 引用格式正则 |
| 参考文献区 | 条目文本 | 标题“参考文献”后分块 |
| 正文区 | 主要正文段落 | 默认剩余区域 |

### 5.4 异常PDF兼容
- 扫描版PDF：若缺少文本块，标记为图像型页面，进入OpenCV特征分析流程
- 加密PDF：捕获异常，记录解析失败，输出可追踪错误
- 多列排版：按列坐标聚类文本块，避免跨列合并

## 6. VisualValidator 设计（阶段3）
### 6.1 图表格式校验
目标：
- 图/表编号与标题关联
- 标题位置校验（图下/表上）
- 正文“见图X/表X”与实际编号匹配

输出问题：`Label_Missing` 或 `Chart_Position_Fault`。

### 6.2 公式格式校验
目标：
- 公式编号提取与右对齐校验
- 公式编号与正文引用匹配

输出问题：`Formula_Missing`、`Formula_Misaligned`。

### 6.3 标题层级校验
目标：
- 基于字体/字号/缩进识别层级
- 发现跳级（如2.1→2.1.2）

输出问题：`Hierarchy_Fault`。

### 6.4 引用标注视觉校验
目标：
- 提取引用标注位置与文本
- 与参考文献区条目做初步关联

输出问题：`Citation_Visual_Fault`（供语义校验进一步融合）。

## 7. AnchorGenerator 设计（阶段4）
锚点生成策略：
- 每个问题绑定 `page_num + bbox`
- 若包含多段证据，生成多条 anchor
- 保留 `anchor_id` 用于前端去重与跳转

前端需要的数据格式以 Markdown 渲染高亮为主，锚点结构需兼容前端定位。

## 8. 与语义判定层协同（阶段5）
协同要点：
- 视觉层输出的 `elements` 直接喂给语义层（特别是引用标注与标题文本）
- 统一去重规则：视觉层问题与语义层问题不重复标注
- 融合输出符合系统API规范的审计结果JSON

## 9. 性能目标与优化方向
目标：单篇≤3s，≥20并发。
优化策略：
- 按页流水线处理，减少全量扫描
- 图片区域预过滤，减少OpenCV计算量
- 结果缓存（同页/同区域坐标复用）

## 10. 验证方式（对齐分工明细）
- PDF解析：10份不同类型PDF，元素提取准确率≥98%
- 视觉校验：20份视觉格式错误样本，准确率≥95%，漏检率≤3%
- 锚点定位：前端跳转/高亮100%精准
- 融合验证：与语义判定无冲突、无重复
- 性能验证：100篇批量测试，平均耗时≤3s

## 11. 交付物清单
- 完整的CV/布局模块实现（按现有代码结构）
- 无状态封装
- requirements.txt + Dockerfile（版本精准）
- 本框架文档作为开发对齐依据
