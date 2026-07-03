"""配置 OpenMemory Server"""
import httpx
BASE = "http://localhost:8765/api/v1/config"

# 1. 重置为默认
r = httpx.post(f"{BASE}/reset")
print("Reset:", r.status_code)

# 2. 完整配置
r = httpx.put(BASE, json={
    "mem0": {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "deepseek-chat",
                "api_key": "sk-49412e1232c54ba8b8a40c854b3edf21",
                "openai_base_url": "https://api.deepseek.com/v1",
                "temperature": 0.1,
                "max_tokens": 2000,
                "ollama_base_url": None,
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "BAAI/bge-m3",
                "api_key": "sk-gsuqwhwfuajautyxuxvwenjhwszvzbbtizkjlugorlzuvqze",
                "openai_base_url": "https://api.siliconflow.cn/v1",
                "ollama_base_url": None,
            }
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": "localhost",
                "port": 6334,
                "embedding_model_dims": 1024,
            }
        },
    }
})
print("Config:", r.status_code, r.text[:300])
