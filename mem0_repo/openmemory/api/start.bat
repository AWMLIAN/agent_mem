@echo off
cd /d "E:\AI Memory\agent_mem\mem0_repo\openmemory\api"
set LLM_PROVIDER=openai
set LLM_MODEL=deepseek-chat
set LLM_API_KEY=sk-83aa21679b634d9e90b866e9a94cc637
set LLM_BASE_URL=https://api.deepseek.com/v1
set EMBEDDER_PROVIDER=openai
set EMBEDDER_MODEL=BAAI/bge-m3
set EMBEDDER_API_KEY=sk-gsuqwhwfuajautyxuxvwenjhwszvzbbtizkjlugorlzuvqze
set EMBEDDER_BASE_URL=https://api.siliconflow.cn/v1
set QDRANT_HOST=localhost
set QDRANT_PORT=6333
set OPENAI_API_KEY=sk-83aa21679b634d9e90b866e9a94cc637
echo Starting OpenMemory MCP Server...
uvicorn main:app --host 0.0.0.0 --port 8765
