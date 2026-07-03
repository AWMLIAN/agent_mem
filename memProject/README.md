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
cp .env.example .env
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
