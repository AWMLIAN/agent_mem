"""Fix OpenMemory: set config via API, then test"""
import httpx, json
BASE = "http://localhost:8765/api/v1/config"

# Reset
httpx.post(f"{BASE}/reset")

# Set full config via PATCH (deep merge)
payload = {
    "mem0": {
        "llm": {
            "provider": "openai",
            "config": {
                "model": "deepseek-chat",
                "api_key": "sk-49412e1232c54ba8b8a40c854b3edf21",
                "openai_base_url": "https://api.deepseek.com/v1",
                "temperature": 0.1,
                "max_tokens": 2000,
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": "BAAI/bge-m3",
                "api_key": "sk-gsuqwhwfuajautyxuxvwenjhwszvzbbtizkjlugorlzuvqze",
                "openai_base_url": "https://api.siliconflow.cn/v1",
            }
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "host": "localhost",
                "port": 6334,
                "embedding_model_dims": 1024,
            }
        }
    }
}

# Try PATCH first
r = httpx.patch(f"{BASE}/", json=payload)
print(f"PATCH: {r.status_code} {r.text[:300]}")

# Verify
r = httpx.get(f"{BASE}/")
print(f"\nConfig: {r.text[:500]}")
