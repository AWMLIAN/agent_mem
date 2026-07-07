# 面向大模型智能体的记忆系统

基于 [mem0](https://github.com/mem0ai/mem0) + OpenMemory MCP Server 构建的智能体记忆管理中台。

## 架构

```
memProject (FastAPI :8000)            OpenMemory MCP Server (:8765)
┌──────────────────────┐    MCP      ┌───────────────────────────┐
│ app/mcp_client.py    │──Streamable─→│ add_memories              │
│ app/api/v1/memory.py │   HTTP      │ search_memory            │
└──────────────────────┘             │ list_memories            │
                                     │ delete_all_memories      │
                                     │     ↓                    │
                                     │ DeepSeek + bge-m3       │
                                     │ Qdrant + PostgreSQL      │
                                     └───────────────────────────┘
```

## 从零开始

### 前置条件

| 软件 | 说明 |
|------|------|
| Python 3.12+ | 运行环境 |
| Docker Desktop | PostgreSQL + Qdrant |
| Git | 拉代码 |
| DeepSeek API Key | [platform.deepseek.com](https://platform.deepseek.com) 注册获取 |
| 硅基流动 API Key | [siliconflow.cn](https://siliconflow.cn) 注册获取 |

---

### 第一步：克隆项目

```bash
git clone <本仓库地址>
cd memProject
```

### 第二步：安装 Python 依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 第三步：配置环境变量

```bash
cp .env .env
```

编辑 `.env`，填入你的 API Key：

```env
DEEPSEEK_API_KEY=sk-你的Key
SILICONFLOW_API_KEY=sk-你的Key
```

### 第四步：启动基础设施

```bash
docker compose up -d
```

确认容器运行：

```bash
docker ps --filter "name=mem-"
# 应看到 mem-postgres 和 mem-qdrant
```

### 第五步：创建数据库表

```bash
python -m alembic revision --autogenerate -m "init_schema"
python -m alembic upgrade head
```

---

### 第六步：搭建 OpenMemory MCP Server

**6.1 克隆 Mem0 仓库**

```bash
cd ..
git clone https://github.com/mem0ai/mem0.git mem0_repo
cd mem0_repo/openmemory/api
```

**6.2 安装依赖**

```bash
pip install -r requirements.txt
```

**6.3 打补丁（3 处修改）**

*补丁 1*：`app/utils/memory.py` — 找到 `get_default_memory_config` 函数，将 LLM/Embedder 环境变量读取部分替换为：

```python
    # --- 硬编码 DeepSeek + SiliconFlow ---
    llm_config = {
        "model": "deepseek-chat",
        "api_key": "sk-你的DeepSeek-Key",
        "openai_base_url": "https://api.deepseek.com/v1",
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    embedder_config = {
        "model": "BAAI/bge-m3",
        "api_key": "sk-你的硅基流动-Key",
        "openai_base_url": "https://api.siliconflow.cn/v1",
    }
```

*补丁 2*：同一文件，在 Qdrant 配置处加 `"embedding_model_dims": 1024`：

```python
# 搜索 "QDRANT_HOST" 找到这段，加一行：
vector_store_config.update({
    "host": os.environ.get('QDRANT_HOST'),
    "port": int(os.environ.get('QDRANT_PORT')),
    "embedding_model_dims": 1024,   # ← 加这一行
})
```

*补丁 3*：`app/mcp_server.py` — 修复两处 mem0 v2.x 兼容性问题：

```python
# list_memories 中（约第 247 行）：
# 改前：memory_client.get_all(user_id=uid)
# 改后：
memory_client.get_all(filters={"user_id": uid})

# search_memory 中（约第 179 行），删除 limit 参数：
# 改前：memory_client.vector_store.search(query=query, vectors=embeddings, limit=10, filters=filters)
# 改后：
memory_client.vector_store.search(query=query, vectors=embeddings, filters=filters)
```

**6.4 创建启动脚本** `start.bat`：

```bat
@echo off
cd /d C:\Users\<你的用户名>\mem0_repo\openmemory\api
set QDRANT_HOST=localhost
set QDRANT_PORT=6333
uvicorn main:app --host 0.0.0.0 --port 8765
```

**6.5 启动**

```bash
start.bat
```

看到 `Uvicorn running on http://0.0.0.0:8765` 即成功。

---

### 第七步：启动 FastAPI

```bash
cd memProject
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

---

### 第八步：验证

```bash
# 健康检查
curl http://localhost:8000/health

# Swagger 文档
# 浏览器打开 http://localhost:8000/docs

# 测试 MCP 4 个工具
python tests/test_mcp_4tools.py
```

---

## 项目结构

```
memProject/
├── app/
│   ├── main.py                  # FastAPI 入口
│   ├── core/                    # 配置、数据库、异常、安全、日志
│   ├── api/v1/                  # 6 组路由（agent/scene/session/task/memory/admin）
│   ├── models/base.py           # 12 张表 ORM
│   ├── schemas/                 # 请求/响应 Pydantic
│   ├── services/mem0_client.py  # mem0 直连（已弃用，保留备用）
│   ├── mcp_client.py            # MCP Client → OpenMemory Server
│   └── middleware/              # 日志、认证、异常处理
├── config/settings.yaml         # 全局配置
├── alembic/                     # 数据库迁移
├── tests/
│   ├── test_api.py              # DeepSeek/SiliconFlow 连通性
│   ├── test_mcp_4tools.py       # MCP 4 工具全量测试
│   └── debug/                   # 调试脚本
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## API 清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/memory/write` | 写入记忆 |
| POST | `/api/v1/memory/search` | 检索记忆 |
| POST | `/api/v1/memory/list` | 列出全部 |
| POST | `/api/v1/memory/delete-all` | 清除全部 |
| POST | `/api/v1/agent/register` | 注册智能体 |
| ... | ... | 共 33 个端点，详见 `/docs` |

## 常见问题

**Q: 8765 端口被占用？**
```bash
netstat -ano | findstr 8765
taskkill /F /PID <进程ID>
```

**Q: add_memories 返回 "Memory system is currently unavailable"？**
A: Qdrant 未启动或配置错误。确认 Docker 运行且 `docker ps` 能看到 Qdrant。

**Q: 延迟很高？**
A: `add_memories` 调用了 DeepSeek API 做记忆抽取，耗时 5-10 秒是正常的。测试时可用 `"infer": false` 跳过大模型，直存原文。

**Q: search_memory 报错？**
A: 确认已打补丁 3（删除 `limit=10` 参数）。

---

## 角色A — 智能体接入与记忆数据写入（已完成 ✅）

> 对齐文档：《核心业务逻辑拆解》《智能体接入与记忆数据写入后端功能任务分工》
> 最近更新：对齐《核心改动》文档 + 《API接口文档-前端对接.md》

### 核心改动点（v2）

| 改动 | 说明 |
|------|------|
| **messages 数组为 Primary** | 前端传入 `messages: [{role, content}]` 多轮对话数组，后端逐条拆分落库 |
| **results 返回格式** | `/memory/write` 返回 `results: [{id, memory, event: ADD/SKIP/MERGE}]`，联调期 Mock 规则抽取 |
| **AUTH_ENABLED 开关** | 开发阶段 `AUTH_ENABLED=false` 跳过鉴权；生产阶段 `true` 强制 X-API-Key 校验 |
| **Session/Task 真DB** | Session（创建/关闭）和 Task（创建/更新进展/查询进度）全部实现真实 DB 操作 |

### 数据流（写入链路）

```
POST /api/v1/memory/write
  │  Body: {user_id, scene_id?, task_id?, messages: [{role, content}]}
  │
  ├─ 1. 鉴权 (deps.py)
  │     开发阶段(AUTH_ENABLED=false) → 跳过，使用默认测试Agent
  │     生产阶段(AUTH_ENABLED=true)  → X-API-Key → SHA256 → t_agent
  │
  ├─ 2. Schema 校验 (MemoryWriteRequest)
  │     messages: [{role: user/assistant/system, content}], ID自动标准化
  │
  ├─ 3. 逐条写入 t_interaction_record
  │     processed=False, turn_index 标记轮次
  │
  ├─ 4. Mock 记忆抽取 (联调期规则)
  │     "我叫xxx"→ADD / "喜欢"→ADD / 问候→SKIP / system→SKIP
  │
  └─ 5. 返回 {"code":0, "data": {"results": [{id, memory, event}]}}
```

### 完成的功能模块

| 模块 | 文件 | 说明 |
|------|------|------|
| **Schema 层** | `app/schemas/memory.py` | `messages` 数组 Primary + `results[{id, memory, event}]` 响应 |
| **校验管线** | `app/services/validation_service.py` | 7步校验管线：必填→类型→ID格式→长度→时间标准化→ID规范化→元数据补全 |
| **同步写入** | `app/api/v1/memory.py` → `/write` | 逐条落库 + Mock抽取 → 返回 results |
| **异步写入** | `app/api/v1/memory.py` → `/async_write` | 鉴权→投递MQ→返回 request_id（MQ不可用降级同步写入） |
| **API日志** | `app/middleware/api_log.py` | fire-and-forget 写 `t_api_log` |
| **鉴权开关** | `app/api/deps.py` + `app/middleware/auth.py` | `AUTH_ENABLED` 开发/生产双模式 |
| **Agent CRUD** | `app/api/v1/agent.py` | 注册(api_key仅一次明文)、分页列表、查询、更新、停用、Key轮换 |
| **Scene CRUD** | `app/api/v1/scene.py` | 创建、分页列表、查询、更新、停用 |
| **Session CRUD** | `app/api/v1/session.py` | 创建、分页列表、查询、更新、关闭(触发压缩) |
| **Task CRUD** | `app/api/v1/task.py` | 创建、分页列表、查询、更新进展、进展摘要(含关联记忆数)、完成 |
| **统一响应** | `app/middleware/error_handler.py` | `{code, message, error_code, trace_id}` + INVALID_PARAM 错误码 |
| **多租户隔离** | `app/api/deps.py` | 停用Agent拒绝、scene权限校验、ID标准化 |

### 测试覆盖

```bash
pytest tests/test_role_a.py -v
# 49 passed — 覆盖:
#   Schema层(10) / Mock抽取(6) / 必填校验(5) / ID标准化(3)
#   时间标准化(3) / 元数据(2) / 一站式管线(2) / 安全工具(4)
#   统一响应(3) / AUTH开关(2) / 边界值(6) / WriteResult(3)
```

### 角色B 待对接项

- **MQ Producer/Consumer**：`_try_deliver_to_mq()` 当前返回 `False`（降级同步写入），需角色B实现
- **正式期记忆抽取**：Mock 规则替换为下游"记忆生成+去重融合"模块的 RPC/MQ 回调
- **统一错误码**：建议共同制定标准业务错误码（40001=Token失效，40002=必填字段缺失）
