# 智学 · 智慧教学问答与作业批改系统

把原来单进程的 `app.py` 拆成一张真正的多 Agent 架构：
**主应用（LLM Router + AgentNetwork）→ 4 个 A2A Agent → 4 个 MCP Server → 工具与数据层**。

老的 `app.py` / `new_main.py` / `rag_qa` / `mysql_qa` 原样保留，互不影响。

> 新系统全部在 `zhixue/` 目录下，从 [快速开始](#二快速开始) 直接跑。
> 原项目的说明在文末 [附录：原项目](#附录原项目itcast_qa_system)。

---

## 一、架构与代码的对应关系

| 层 | 组件 | 端口 | 代码 |
|---|---|---|---|
| 主应用 | 主应用（LLM Router / AgentNetwork / 结果总结） | **8000** | `zhixue/app/main.py` `router_agent.py` `agent_network.py` `summarizer.py` |
| 主应用 | 课本答疑（RAG） | — | `zhixue/app/qa.py` |
| A2A Agent | 文档生成 Agent | **5010** | `zhixue/agents/docgen_agent.py` |
| A2A Agent | 出题 Agent | **5011** | `zhixue/agents/question_agent.py` |
| A2A Agent | 作业批改 Agent | **5012** | `zhixue/agents/grading_agent.py` |
| A2A Agent | 学情分析 Agent | **5013** | `zhixue/agents/analysis_agent.py` |
| MCP | MCP DocGen | **8010/mcp** | `zhixue/mcp_servers/docgen_mcp.py` |
| MCP | MCP Question | **8011/mcp** | `zhixue/mcp_servers/question_mcp.py` |
| MCP | MCP Grading | **8012/mcp** | `zhixue/mcp_servers/grading_mcp.py` |
| MCP | MCP Analysis | **8013/mcp** | `zhixue/mcp_servers/analysis_mcp.py` |
| 工具与数据 | 课本检索 / Word 模板 | — | `zhixue/tools/docgen_tools.py` `zhixue/vector.py` |
| 工具与数据 | 题库检索 / 组卷 | — | `zhixue/tools/question_tools.py` |
| 工具与数据 | OCR / 答案比对 | — | `zhixue/tools/grading_tools.py` |
| 工具与数据 | Text-to-SQL / 学情 | — | `zhixue/tools/analysis_tools.py` |

架构图上的**虚线**（Agent 之间横向调用）由 `GradingAgent` 在批改完成后
通过 `A2AClient` 通知 `AnalysisAgent` 写入错题记录库实现，
返回结果里会显示 `通道：a2a`。

---

## 二、快速开始

### 1. 准备配置

仓库里不含 `config.ini`（里面有 API Key 和数据库密码，已被 `.gitignore` 排除）。
先复制一份出来填自己的值：

```powershell
copy config.example.ini config.ini
```

至少要改这几项：

```ini
[llm]
dashscope_api_key = 你的 DashScope API Key   # 否则模型调用会 401，系统降级为规则输出

[zhixue]
mysql_password = 你的 MySQL 密码
```

### 2. 装依赖

```powershell
pip install -r requirements-zhixue.txt
```

如果你已经装过 `fastmcp`，而 `fastapi` 报
`Router.__init__() got an unexpected keyword argument 'on_startup'`，
说明 starlette 被顶到了 1.x，需要把 fastapi 一起升上去：

```powershell
pip install -U "fastapi>=0.140"
```

### 3. 生成仿真数据

```powershell
python -m zhixue.data.seed --reset
```

会生成：20 名学生、19 个知识点、46 道题、10 份作业、约 166 份提交、
约 397 条批改明细、153 条错题记录，以及 4 套 Word 模板和答题卡图片。

数据落在 MySQL 的 **`zhixue`** 库（不动原来的 `subjects_kg`）。

### 4. 启动

```powershell
python run_all.py                  # 启动全部 9 个进程
python run_all.py --check          # 只做环境自检
python run_all.py --only main      # 只起主应用
python run_all.py --mode local     # 单进程模式（不需要 MCP/A2A SDK）
```

浏览器打开 <http://127.0.0.1:8000>。

---

## 二·五、模型权重说明（仓库里没有，需要自己放）

仓库只包含代码、文档和少量示例数据。**模型权重约 12 GB，被 `.gitignore` 排除了**
（`*.bin` / `*.safetensors` / `*.pt` / `*.onnx` 等）。

智学本身在**没有这些模型时也能完整跑通**（检索自动降级为 BM25 关键词检索）。
想启用向量检索 / OCR / 意图分类，按下面这张表把权重放回对应目录：

| 目录 | 模型 | 用途 | 没有时的影响 |
|---|---|---|---|
| `rag_qa/models/bge-m3` | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | 向量化（1024 维） | 检索降级为 BM25 |
| `rag_qa/models/bge-reranker-large` | [BAAI/bge-reranker-large](https://huggingface.co/BAAI/bge-reranker-large) | 重排 | 只影响原项目的 RAG 精排 |
| `rag_qa/models/nlp_bert_document-segmentation-chinese-base` | [damo/nlp_bert_document-segmentation_chinese-base](https://modelscope.cn/models/damo/nlp_bert_document-segmentation_chinese-base) | 长文分段 | 只影响原项目的文档切分 |
| `rag_qa/core/bert_query_classifier` | 本项目自训（`rag_qa/core/train_bert.py`） | 通用/专业二分类 | 只影响原项目的查询分类 |
| `rag_qa\core\output`、`bert_results`、`bert_outputs` | 训练 checkpoint | 训练产物，可删 | 无 |

下载示例（HuggingFace 镜像）：

```powershell
pip install -U "huggingface_hub[cli]"
huggingface-cli download BAAI/bge-m3 --local-dir rag_qa/models/bge-m3
huggingface-cli download BAAI/bge-reranker-large --local-dir rag_qa/models/bge-reranker-large
```

放好之后重建一次向量索引：

```powershell
python -c "from zhixue.vector import get_retriever; print(get_retriever().rebuild())"
```

---

## 三、试着说这几句

| 输入 | 走哪条链路 |
|---|---|
| `给 Python 装饰器出 3 道题` | LLM Router → 出题 Agent → 题库向量库 → 作业下发 |
| `批改 S00001 的 HW00001` | 批改 Agent → 复用已有作答重新批改 → **A2A 通知**学情分析落错题 |
| 点「上传答题卡」选 `zhixue/data/outputs/answer_sheet_HW00001_S00001.png`，再发 `批改 S00001 的 HW00001` | 批改 Agent → **OCR 识别** → 比对 → A2A 落错题 |
| `分析一下 S00001 的学情` | 学情 Agent → Text-to-SQL/成绩库 → 学生画像 |
| `生成装饰器的学习计划` | 文档 Agent → 课本检索 → Word 模板渲染 |
| `解释一下 Java 线程池的核心参数` | 主应用 RAG 答疑（带课本引用） |
| `批改作业` → `S00001 和 HW00002` | 信息缺失 → 追问 → 多轮补槽后继续 |

> 种子数据保证 **S00001 交齐了全部作业**，并且 `HW00001~HW00003` 都生成了答题卡图片，
> 所以上面这几句可以直接照着敲。

---

## 四、接口清单（主应用 :8000）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 对话（返回结构化 JSON + 卡片） |
| POST | `/api/chat/stream` | 对话（SSE：`route` / `agent` / `token` / `card` / `end`） |
| GET | `/api/students` | 学生列表 |
| GET | `/api/homeworks` | 作业列表 |
| GET | `/api/agents` | 四个 Agent 在线状态 |
| GET | `/api/retrieval` | 向量检索后端状态 |
| GET/DELETE | `/api/session/{id}` | 会话历史 / 清空 |
| POST | `/api/upload` | 上传答题卡图片 |
| GET | `/api/files/{name}` | 下载生成的文档 / 图片 |
| GET | `/health` | 健康检查 |

每个 Agent（:5010~:5013）都提供：

* `POST /task/send` —— 架构图上的任务入口（接受完整 TaskRequest 或 `{"text": "..."}`）
* `GET /.well-known/agent-card.json` —— A2A Agent Card
* `GET /health`、`GET /skills`、`GET /agent/info`
* 装了 `a2a-sdk` 时额外挂载标准 A2A JSON-RPC 路由（`message/send`）

每个 MCP Server（:8010~:8013）暴露标准的 `/mcp`（streamable HTTP）端点，
可以用 MCP Inspector 或 `fastmcp.Client` 直接调用。

---

## 五、关键数据契约

```python
RouterDecision   # LLM Router 输出：intent / slots / missing / reply
TaskRequest      # 主应用 -> Agent：task_id / intent / slots / history
TaskResult       # Agent -> 主应用：status / text / data / artifacts / elapsed
```

意图与必填槽位（`zhixue/schemas.py`）：

| intent | 负责方 | 必填槽位 |
|---|---|---|
| `doc_gen` | docgen Agent | `topic` |
| `question_gen` | question Agent | `knowledge_point` |
| `grading` | grading Agent | `student_id`、`homework_id` |
| `analysis` | analysis Agent | `student_id` |
| `textbook_qa` | 主应用 RAG | `question` |
| `chitchat` | 主应用 | — |

---

## 六、降级策略（没有这些依赖也能跑）

| 依赖 | 缺失时的行为 |
|---|---|
| Redis | 自动换进程内字典缓存，会话补槽照常 |
| Milvus / BGE-M3 | 向量检索降级为 BM25 关键词检索（结果里 `backend=keyword`） |
| DashScope API Key | LLM 调用熔断，Agent 走规则化输出，流程不断 |
| `fastmcp` | `tool_transport=local`，Agent 进程内直调同一批函数 |
| `a2a-sdk` | `network_transport=a2a` 自动回退到 `POST /task/send` |

把开关写进 `config.ini`：

```ini
[zhixue]
mysql_password = root
mysql_database = zhixue
tool_transport = mcp      # mcp | local
network_transport = a2a   # a2a | local
```

---

## 七、常见问题

**Q：模型没反应 / 日志里全是 401？**
`config.ini` 里的 `dashscope_api_key` 已失效。换成有效的 Key，
或设置环境变量 `DASHSCOPE_API_KEY`。系统在无 Key 时仍可完整演示（走规则化输出）。

**Q：Milvus 明明装了却还是关键词检索？**
检查 `docker ps` 里 Milvus 是否在跑，以及 `config.ini` 的 `[milvus]` 地址。
连接成功后执行一次 `python -c "from zhixue.vector import get_retriever; print(get_retriever().rebuild())"`
即可把课本和题库灌进向量库。

**Q：只想看单机版？**
原来的 `app.py` 没动，`python app.py` 仍可运行（端口 8003）。

---

## 八、目录结构

```
zhixue/
  config.py            统一配置（环境变量 > config.ini > 默认值）
  schemas.py           RouterDecision / TaskRequest / TaskResult
  store.py             MySQL + Redis（可降级）
  vector.py            Milvus + BM25 双通道检索
  llm.py               DashScope 封装（含 401 熔断）
  tool_client.py       Agent 调工具（MCP / local）
  registry.py          意图 -> Agent 路由表
  a2a/                 A2A 协议层（cards / server / client）
  agents/              4 个业务 Agent
  mcp_servers/         4 个 MCP Server
  tools/               纯业务逻辑（无协议依赖，可直接单测）
  app/                 主应用 + 前端
  data/                建表 / 仿真内容 / 模板 / 种子脚本
run_all.py             一键启动 9 个进程
```

---

## 附录：原项目（Itcast_qa_system）

仓库里保留着拆分之前的单进程版本，作为对照和兜底，**没有改动过**。

| 入口 | 说明 | 端口 |
|---|---|---|
| `app.py` | 原 FastAPI 服务（`IntegratedQASystem` + 前端 `static/index.html`） | 8003 |
| `new_main.py` | 原命令行问答：BM25 精确问答 + RAG 兜底 | — |
| `mysql_qa/` | MySQL 业务库、Redis 缓存、BM25 检索 | — |
| `rag_qa/` | 文档解析（PDF/Word/PPT/图片 OCR）、长文分段、向量库、查询分类、RAG 评估 | — |
| `demo/` | 课程练习（logging / fastapi / redis） | — |

```powershell
python app.py            # 原单机版服务
python new_main.py       # 原命令行版
```

两部分的关系：

* 原项目的 `rag_qa` / `mysql_qa` 是智学的**素材来源**——智学把其中的
  RAG 检索、BM25、OCR 能力重新包成了 `zhixue/tools/` 里的工具；
* 两者共用同一份 `config.ini`（智学额外读 `[zhixue]` 段做覆盖）；
* 数据库彼此独立：智学用 `zhixue` 库，原项目用 `subjects_kg` 库。
