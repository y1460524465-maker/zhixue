# 智学 · 架构与实现说明

本文对应你给的那张架构图，说明**一次请求从进入系统到返回界面**的完整流程、
每一层的实现方式，以及当初的落地顺序。

---

## 一、一次请求的完整时序

以「批改 S00001 的 HW00002」为例：

1. 前端 `POST /api/chat/stream` → 主应用 `zhixue/app/main.py`
2. **LLM Router**（`router_agent.py`）
   - 先查 Redis 里的会话草稿（多轮补槽用）
   - 一次 LLM 调用同时得到：意图 `grading`、槽位 `{student_id, homework_id}`、置信度
   - 对照 `REQUIRED_SLOTS` 判断信息是否齐全
3. **分支**
   - 缺信息 → 直接返回 `type=ask_user` 的追问，流程回到"用户输入"（草稿留待下一轮合并）
   - 信息齐全 → 进入 AgentNetwork
4. **AgentNetwork**（`agent_network.py`）：按 `INTENT_TO_AGENT` 路由表
   找到 `grading`，用 `A2AClient` 发 `message/send` 到 `http://127.0.0.1:5012`
5. **GradingAgent**（`agents/grading_agent.py`）
   - 通过 `ToolClient` 调自己的 MCP Server `http://127.0.0.1:8012/mcp`
   - `get_homework` 取标准答案 → `grade_submission` 逐题比对并落库
   - 客观题规则匹配、主观题 LLM 评分（失败降级关键词覆盖）
6. **横向 A2A 调用**（架构图虚线）
   - 批改完成后，GradingAgent 用 `A2AClient` 调 `http://127.0.0.1:5013`
   - AnalysisAgent 收到 `action=write_mistakes`，执行 `write_mistake_records`
     把错题写进 `mistake_record` 表
7. **结果回传**：两个 Agent 各自返回 `TaskResult`（结构化 data + 文字）
8. **结果优化**（`summarizer.py`）：LLM 把多 Agent 结果合成一段人话，
   并把 data 转成前端卡片（`grading` / `analysis` / `questions` / `document` / `qa`）
9. **界面展示**：SSE 依次推 `route → agent → token… → card → end`，
   同时把问答写入 `conversation` 表

---

## 二、分层实现要点

### 主应用层（:8000）

| 组件 | 文件 | 职责 |
|---|---|---|
| LLM Router | `app/router_agent.py` | 意图识别 + 槽位抽取 + 缺信息判断 + 多轮补槽 |
| AgentNetwork | `app/agent_network.py` | 意图→Agent 路由、并发派发、健康探测 |
| 结果总结 | `app/summarizer.py` | 多结果合并、卡片构造 |
| 课本答疑 | `app/qa.py` | `textbook_qa` 走主应用自身 RAG |

Router 的双通道设计：优先 LLM，失败或不可用时走规则（关键词 + 知识点反查），
保证没有 API Key 也能演示完整流程。

### A2A Agent 层（:5010~:5013）

每个 Agent 都是同一套骨架 `agents/base.py`：

```
TaskRequest → run() → 调 MCP 工具 → LLM 组织语言 → TaskResult
```

对外同时暴露：

* `POST /task/send`（架构图上的入口）
* 标准 A2A：`/.well-known/agent-card.json` + JSON-RPC `message/send`
  （由 `a2a/server.py` 里的 `AgentService._mount_a2a` 挂载）

### MCP 服务层（:8010~:8013/mcp）

用 `fastmcp.FastMCP` 起 streamable HTTP 服务，工具函数直接转发到 `zhixue/tools/*`。
这一层刻意做得很薄，真正的逻辑都在 `tools/` 里，所以：

* 可以单独用 MCP Inspector 调；
* 可以 `tool_transport=local` 时在进程内直调；
* 可以写单测，不用起服务。

### 工具与数据层

| 工具 | 实现 | 数据源 |
|---|---|---|
| RAG 课本检索 | `vector.KnowledgeRetriever.search_textbook` | Milvus `zhixue_textbook` / BM25 降级 |
| RAG 题库检索 | `vector.KnowledgeRetriever.search_questions` | Milvus `zhixue_question` / BM25 降级 |
| Word 模板生成 | `tools/docgen_tools.render_word` | `word_template` 表 + `data/templates/*.docx` |
| OCR 识别 | `tools/grading_tools.ocr_extract` | rapidocr；无引擎时读同名 .txt |
| 答案比对 | `tools/grading_tools.compare_answer` | 规则 + LLM |
| Text-to-SQL | `tools/analysis_tools.text_to_sql` | LLM 生成只读 SQL |
| 学生成绩库 | `score_record` | MySQL |
| 错题记录库 | `mistake_record` | MySQL |
| 作业答案库 | `homework_answer` / `grading_result` | MySQL |

---

## 三、数据模型（13 张表）

```
student            学生
knowledge_point    知识点
question_bank      题库（题目向量库的源数据）
homework           作业
homework_question  作业-题目关联
homework_answer    作业答案库（标准答案 + 评分要点）
submission         提交记录
grading_result     批改明细（逐题）
score_record       学生成绩库
mistake_record     错题记录库
textbook_chunk     课本语料（课本向量库的源数据）
word_template      Word 模板库
conversation       会话历史
```

建表语句在 `zhixue/data/schema.py`。**刻意不使用**
`DATETIME DEFAULT CURRENT_TIMESTAMP`（需 MySQL 5.6.5+）与 `JSON` 列（需 5.7+），
因为本机 MySQL 是 5.5.27；时间戳由应用层显式写入。
Text-to-SQL 的提示词里也明确禁用了窗口函数与 CTE。

---

## 四、落地顺序（当初的实施计划）

| 阶段 | 内容 | 验收标准 | 状态 |
|---|---|---|---|
| 0 | 配置可移植化 + 数据模型 + 仿真数据 | `python -m zhixue.data.seed --reset` 成功，13 张表有数据 | ✅ |
| 1 | 工具与数据层（纯业务函数） | 检索/选题/OCR/比对/Text-to-SQL 全部可直接调用 | ✅ |
| 2 | MCP 服务层（4 个 Server） | 每个 `/mcp` 能列工具并成功调用 | ✅ |
| 3 | A2A 协议层 + 4 个 Agent | `POST /task/send` 与 A2A `message/send` 均返回 TaskResult | ✅ |
| 4 | 主应用（Router + Network + 总结 + 前端） | 前端能跑通 5 条主链路 | ✅ |
| 5 | 跨 Agent 协作（批改 → 学情落错题） | 批改返回里显示 `通道：a2a` | ✅ |
| 6 | 降级与健壮性 | 无 Redis / 无 Milvus / 无 Key / 无 SDK 时仍可用 | ✅ |

---

## 五、验证记录

本机实测（MySQL 5.5.27 / 无 Redis / 无 Milvus / DashScope Key 已失效）：

```
run_all.py --check        9 项自检通过
端口                      8000 / 5010-5013 / 8010-8013 全部监听
MCP                       list_tools = search_textbook, list_templates, render_word, ...
A2A                       a2a-sdk 1.2.2 客户端调用成功（非降级路径）
出题                      "给 Python 装饰器出 3 道题" → 生成作业 HW00012
批改                      "批改 S00001 的 HW00002" → 9.7/40，错题同步通道 a2a
答疑                      "解释一下 Java 线程池的核心参数" → 命中课本 4 段并给出引用
生成文档                  "生成装饰器的学习计划" → study_plan_*.docx
多轮补槽                  "批改作业" → 追问 → "S00001 和 HW00002" → 继续批改
SSE                       route → agent → 92 × token → card → end
```

在**没有 Redis、没有 Milvus、模型 Key 失效**的情况下全链路依然跑通，
说明降级路径有效；补上这三样即可获得向量检索与真正的 LLM 输出。

---

## 六、后续可扩展的方向

1. **真实题库接入**：把 `zhixue/data/content.py` 换成教研的正式题库导入脚本。
2. **纸质答题卡**：现在用印刷体答题卡验证 OCR，接入手写体模型后可换真实作业。
3. **学习路径推荐**：AnalysisAgent 已经产出薄弱知识点，可再挂一个"推荐下一题"的工具。
4. **教师端**：`frequent_mistakes` 已经是教研视角的数据，可单独做一个看板。
5. **Agent 观测**：现在日志已带 `task_id`，可以接 OpenTelemetry 做全链路追踪。
