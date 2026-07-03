# -*- coding: utf-8 -*-
"""分别测试 DeepSeek 和硅基流动 API 是否通"""
import os
from dotenv import load_dotenv
load_dotenv(".env")

deepseek_key = os.getenv("DEEPSEEK_API_KEY")
silicon_key = os.getenv("SILICONFLOW_API_KEY")

print("=" * 50)
print("1. 测试 DeepSeek LLM...")
print("=" * 50)
try:
    from openai import OpenAI
    c = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
    r = c.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "你好，请说一句话"}],
        max_tokens=50,
    )
    print("✅ DeepSeek 连接成功:", r.choices[0].message.content)
except Exception as e:
    print("❌ DeepSeek 失败:", e)

print()
print("=" * 50)
print("2. 测试硅基流动 bge-m3 Embedding...")
print("=" * 50)
try:
    from openai import OpenAI
    c = OpenAI(api_key=silicon_key, base_url="https://api.siliconflow.cn/v1")
    r = c.embeddings.create(
        model="BAAI/bge-m3",
        input="你好世界",
    )
    dim = len(r.data[0].embedding)
    print(f"✅ 硅基流动连接成功，向量维度: {dim}")
except Exception as e:
    print("❌ 硅基流动失败:", e)
