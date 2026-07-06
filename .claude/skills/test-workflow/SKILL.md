---
name: test-workflow
description: 智能体记忆系统完整测试流程。从 Docker 启动到逐层验证 mem0、检索服务、API、MCP 工具。TRIGGER: 用户要求测试项目、验证功能、启动并测试时。
---

# 完整测试流程

## 终端 1：Docker

```cmd
cd C:\Users\lenovo\Desktop\claudecode\memProject
docker compose up -d
docker ps --filter "name=mem-"
```

## 终端 2：OpenMemory MCP Server

```cmd
netstat -ano | findstr 8765
:: 有进程则 taskkill /F /PID <PID>
del C:\Users\lenovo\Desktop\claudecode\mem0_repo\openmemory\api\openmemory.db
C:\Users\lenovo\Desktop\claudecode\mem0_repo\openmemory\api\start.bat
```

确认 `Uvicorn running on http://0.0.0.0:8765`

## 终端 3：FastAPI

```cmd
cd C:\Users\lenovo\Desktop\claudecode\memProject
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

## 终端 4：逐步测试

### Step 1 — mem0 初始化

```cmd
.venv\Scripts\python.exe tests\test_step1_init.py
```

预期: `初始化: OK`，搜索 >=1 条

### Step 2 — 检索服务

```cmd
.venv\Scripts\python.exe tests\test_step2_retrieval.py
```

预期: `total_candidates > 0`

### Step 3 — HTTP 接口

```cmd
.venv\Scripts\python.exe tests\test_step3_api.py
```

预期: 写入200 + 检索200 + >=1 条

### Step 4 — MCP 4 工具

```cmd
.venv\Scripts\python.exe tests\test_mcp_4tools.py
```

预期: add→list→search→delete→清空 全部通过

## 常见问题

| 症状 | 解决 |
|------|------|
| 8765 端口占用 | `netstat -ano \| findstr 8765` + `taskkill /F /PID <PID>` |
| Memory system unavailable | Qdrant 未启动 |
| search 返回空 | Step 1 检查 mem0 初始化状态 |
| CMD curl 换行 | 用 Python 测试脚本 |
