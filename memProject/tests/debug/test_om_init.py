"""模拟 OpenMemory 的 mem0 初始化，找出 illegal request line 原因"""
import os, sys
sys.path.insert(0,'.')
from dotenv import load_dotenv
load_dotenv("C:/Users/lenovo/Desktop/claudecode/mem0_repo/openmemory/api/.env")

from mem0 import Memory

# 完全模拟 OpenMemory 的 get_default_memory_config() 输出
config = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": "localhost",
            "port": 6334,
            "collection_name": "openmemory",
            "embedding_model_dims": 1024,
        }
    },
    "llm": {
        "provider": "openai",
        "config": {
            "model": "deepseek-chat",
            "api_key": os.getenv("LLM_API_KEY"),
            "openai_base_url": os.getenv("LLM_BASE_URL"),
            "temperature": 0.1,
            "max_tokens": 2000,
        }
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "BAAI/bge-m3",
            "api_key": os.getenv("EMBEDDER_API_KEY"),
            "openai_base_url": os.getenv("EMBEDDER_BASE_URL"),
        }
    },
    "version": "v1.1"
}

print("Config:", config)
print()
print("Initializing mem0...")
try:
    m = Memory.from_config(config_dict=config)
    print("OK: init success")
except Exception as e:
    print(f"FAIL: {e}")
