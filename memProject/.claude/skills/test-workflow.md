---
name: test-workflow
description: 智能体记忆系统完整测试流程。从 Docker 启动到逐层验证 mem0 初始化、检索服务、HTTP 接口、MCP 工具。TRIGGER: 用户要求测试项目、验证功能、跑测试流程、启动并测试时。
---

# 完整测试流程 Skill

你将按顺序引导用户完成以下步骤。每一步先输出指令，等待用户确认后再继续。

## 第一步：启动 Docker

```cmd
cd C:\Users\lenovo\Desktop\claudecode\memProject
docker compose up -d
docker ps --filter "name=mem-"
```

确认看到 `mem-postgres` 和 `mem-qdrant` 两个容器。如果没有，让用户检查 Docker Desktop 是否在运行。

## 第二步：启动 OpenMemory MCP Server

```cmd
:: 杀掉旧进程
netstat -ano | findstr 8765
:: 有结果则 taskkill /F /PID <PID>

:: 删除旧数据库
del C:\Users\lenovo\Desktop\claudecode\mem0_repo\openmemory\api\openmemory.db

:: 启动
C:\Users\lenovo\Desktop\claudecode\mem0_repo\openmemory\api\start.bat
```

确认看到 `Uvicorn running on http://0.0.0.0:8765`。

## 第三步：启动 FastAPI

```cmd
cd C:\Users\lenovo\Desktop\claudecode\memProject
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

## 第四步：逐步测试

按顺序执行，每步完成后检查结果再继续下一步。

### Step 1：验证 mem0 初始化 + 搜索

```cmd
cd C:\Users\lenovo\Desktop\claudecode\memProject
.venv\Scripts\python.exe tests\test_step1_init.py
```

预期：`初始化: OK`，搜索返回 ≥1 条结果。如果失败，检查 Qdrant 是否运行、config/settings.yaml 中 LLM/Embedder API Key 是否正确。

### Step 2：验证检索服务（过滤 + 格式化）

```cmd
.venv\Scripts\python.exe tests\test_step2_retrieval.py
```

预期：`total_candidates > 0`，结果包含 `memory_type`、`relevance_score` 等字段。

### Step 3：验证 HTTP 接口全链路

```cmd
.venv\Scripts\python.exe tests\test_step3_api.py
```

预期：写入 200，检索 200，返回 ≥1 条结果。

### Step 4：验证 MCP 4 个工具

```cmd
.venv\Scripts\python.exe tests\test_mcp_4tools.py
```

预期：add→list→search→delete→清空验证 全部通过。

## 常见问题速查

| 症状 | 排查 |
|------|------|
| 8765 端口占用 | `netstat -ano \| findstr 8765` → `taskkill /F /PID <PID>` |
| Database connection failed | `docker compose up -d` |
| Memory system unavailable | Qdrant 未启动或 OpenMemory .env 配置错误 |
| search 返回空 | Step 1 确认 mem0_client 初始化OK |
| CMD curl 换行问题 | 改用 Python 测试脚本，不用 curl |
| DeepSeek 超时 | 正常，单次 5-10 秒。`categorization.py` 已修复走 DeepSeek |
