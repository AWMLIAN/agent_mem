# -*- coding: utf-8 -*-
"""
静态检查 — 数据库迁移、ORM 定义、清理逻辑的正确性验证。

不依赖服务器、数据库连接或测试数据，仅解析代码和文件系统。
"""

import os
import re


ALEMBIC_DIR = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")


def test_alembic_revision_ids_are_unique():
    """每个 revision ID 在迁移目录中只能出现一次（定义）"""
    revision_files = [
        f for f in os.listdir(ALEMBIC_DIR)
        if f.endswith(".py") and f != "__init__.py"
    ]

    seen = {}  # revision_id -> [filenames]
    for fname in sorted(revision_files):
        fpath = os.path.join(ALEMBIC_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'revision["\']?\s*[:=]\s*["\']([a-f0-9]+)["\']', content)
        if match:
            rev = match.group(1)
            seen.setdefault(rev, []).append(fname)

    duplicates = {rev: files for rev, files in seen.items() if len(files) > 1}
    assert not duplicates, f"重复的 revision ID: {duplicates}"


def test_memory_model_has_single_memory_scope_definition():
    """Memory 模型中 memory_scope = Column(...) 只能声明一次"""
    model_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "models", "base.py"
    )
    with open(model_path, encoding="utf-8") as f:
        lines = f.readlines()

    count = 0
    in_memory = False
    for line in lines:
        if re.match(r"class Memory\b", line):
            in_memory = True
        if in_memory:
            if re.match(r"class \w", line) and "Memory" not in line:
                break
            if re.search(r"memory_scope\s*=\s*Column\s*\(", line):
                count += 1

    assert count == 1, f"memory_scope 应声明 1 次，实际 {count}"


def test_purge_deleted_unified_condition():
    """purge_deleted 的统计条件与删除条件应使用同一表达式"""
    service_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "services", "memory_store.py"
    )
    with open(service_path, encoding="utf-8") as f:
        content = f.read()

    # 确认使用 coalesce 统一条件
    assert "coalesce(Memory.deleted_at, Memory.updated_at)" in content or \
           "sa_func.coalesce(Memory.deleted_at, Memory.updated_at)" in content, \
           "应使用 coalesce(deleted_at, updated_at) 统一清理条件"

    # 确认删除前收集 memory_id
    assert "purge_ids" in content, "应在删除前收集 memory_id"

    # 确认删除后使用收集到的 ID 清理 Qdrant
    assert "qdrant.delete_vectors(purge_ids)" in content or \
           "qdrant.delete_vectors(purge_ids)" in content, \
           "应使用预收集的 memory_id 清理 Qdrant"
