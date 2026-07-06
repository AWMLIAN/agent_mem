# 工作报告：记忆生成与去重融合功能实现

**日期**：2026-07-06  
**作者**：Claude Fable 5 (AI 辅助开发)  
**分支**：master  
**关联文档**：《面向大模型智能体的记忆系统功能设计文档》— "记忆生成与去重融合功能"章节

---

## 一、概述

按照设计文档中"记忆生成与去重融合功能"的完整规格，在 memProject 中实现了三大核心能力的独立模块：

1. **关键记忆抽取** — 从对话数据中提取关键事实（业务对象、约束条件、确认事项）、任务状态（进展、已完成、待处理）、历史决策（方案、依据、结果）
2. **结构化记忆生成** — 将抽取结果通过 LLM 转化为标准化的记忆对象（content + summary + key_points + memory_type + tags + entities + importance + confidence）
3. **去重融合处理** — 基于向量语义相似度 + 关键词 Jaccard 重合 + 标识一致性判断的多阶段去重引擎，支持 DISCARD/MERGE/UPDATE_EXISTING/KEEP_NEW 四种动作

## 二、技术架构

### 设计原则
- **零侵入**：所有新增功能放在独立文件中，不修改现有业务逻辑代码
- **模块化**：每个服务独立可测试，接口清晰，方便其他团队成员接轨
- **复用现有基础设施**：使用已配置的 DeepSeek LLM、SiliconFlow Embedding、Qdrant、PostgreSQL

### 新增文件（14 个）

```
memProject/app/
├── prompts/                              # Prompt 模板（5 个文件）
│   ├── __init__.py
│   ├── key_fact_extraction.py            # 关键事实抽取
│   ├── task_state_extraction.py          # 任务状态抽取
│   ├── decision_extraction.py            # 历史决策抽取
│   └── memory_generation.py             # 记忆生成
├── services/                             # 核心服务（6 个文件）
│   ├── llm_client.py                     # DeepSeek LLM 客户端
│   ├── embedding_client.py              # SiliconFlow 嵌入客户端
│   ├── memory_extractor.py              # 三大抽取器 + Facade
│   ├── memory_generator.py              # 结构化记忆生成
│   ├── memory_dedup.py                  # 多阶段去重引擎
│   └── memory_pipeline.py              # 完整流水线编排
├── core/
│   └── qdrant_client.py                 # Qdrant gRPC 单例
├── schemas/
│   └── generation.py                    # Pydantic 模型
├── api/v1/
│   └── generation.py                    # API 端点（4 个）
└── tests/
    ├── test_memory_generation.py         # 单元测试（24 个）
    └── debug/
        └── test_generation_e2e.py        # E2E 演示脚本
```

### 修改文件（2 个，各 1 行）

| 文件 | 改动 |
|------|------|
| `app/api/v1/router.py` | 添加 `generation` 路由注册 |
| `app/services/__init__.py` | 合并双方改动：添加新服务导出 + 保留上游 validation_service 导出 |

## 三、核心模块说明

### 3.1 关键记忆抽取（Memory Extractor）

三个独立提取器并行运行，每个有定制化的 LLM Prompt：

| 提取器 | 输出 | 字段 |
|--------|------|------|
| KeyFactExtractor | KeyFactsResult | business_objects, constraints, confirmations |
| TaskStateExtractor | TaskStateResult | current_progress, completed_items, pending_items |
| DecisionExtractor | DecisionResult | confirmed_plans, selection_rationale, execution_results |

MemoryExtractor Facade 按 `extraction_types` 参数调度子提取器并行执行，聚合到统一的 ExtractionResult。

### 3.2 结构化记忆生成（Memory Generator）

将 ExtractionResult 通过 LLM 转化为 MemoryCandidate 列表，每条包含：
- content：独立可检索的记忆文本
- summary：1-2 句摘要
- key_points：2-5 条要点
- memory_type：fact / preference / task_state / decision / constraint / process
- tags / entities / importance / confidence

LLM 负责智能分组：相关事实合并，不相关事实分开。

### 3.3 去重融合引擎（Dedup Service）

六阶段流水线：

```
Stage 1: 向量相似度检索 → Qdrant 语义搜索 top-5 (threshold ≥ 0.70)
Stage 2: 数据库加载 → 从 PostgreSQL t_memory 表加载完整记忆
Stage 3: 关键词重合 → Jaccard(entities + tags + 提取名词) 打分
Stage 4: 标识一致性 → task_id 相同 或 entities 重叠 ≥ 2
Stage 5: 综合决策:
  composite = 0.5×vector_score + 0.3×keyword_overlap + 0.2×identity_bonus
  ≥ 0.90              → DISCARD
  0.80-0.90 + identity → UPDATE_EXISTING
  0.65-0.80 + !identity → MERGE
  < 0.65               → KEEP_NEW
Stage 6: MERGE 执行 → content 追加 + key_points 去重 + entities 并集 + 取 max importance/confidence
```

### 3.4 完整流水线（Memory Pipeline）

```
extract(text) → generate(extraction_result) → dedup(candidates) → store(DB + Qdrant)
```

单例模式，惰性初始化子服务。支持同步/批量两种模式。

## 四、API 端点

| Method | Path | 说明 |
|--------|------|------|
| POST | `/api/v1/memory/generate` | 同步生成记忆（完整流水线） |
| POST | `/api/v1/memory/generate/batch` | 批量生成（最多 50 条文本） |
| POST | `/api/v1/memory/generate/async` | 异步提交（返回 request_id） |
| GET | `/api/v1/memory/generate/{request_id}/status` | 查询异步任务状态 |

所有端点返回标准 `{"code": 0, "message": "ok", "data": {...}}` 格式，与现有 API 一致。

## 五、测试结果

### 单元测试：24/24 全部通过

覆盖范围：
- LLM Client（正常请求、JSON 解析、regex 降级恢复、异常处理）
- Embedding Client（单条嵌入 1024 维、批量拆分 32 条/批）
- KeyFactExtractor / TaskStateExtractor / DecisionExtractor（Mock LLM 验证）
- MemoryExtractor Facade（类型调度、并行执行、空结果处理）
- MemoryGenerator（记忆生成、空抽取结果、候选验证与裁剪）
- DedupService（完整决策矩阵 4 条路径、关键词 Jaccard 计算、标识判定、内容合并、Qdrant 不可用降级）

### E2E 测试：全部通过

使用真实 DeepSeek LLM + SiliconFlow Embedding 验证：
- LLM 连接正常，JSON 结构化抽取全部成功
- 从 329 字对话中提取：5 个业务对象 + 3 个约束条件 + 4 个确认事项 + 3 个已完成项 + 3 个待处理项
- 生成 5 条带评分的标准化记忆（fact / constraint / decision / task_state）
- 去重决策矩阵 DISCARD → UPDATE_EXISTING → MERGE → KEEP_NEW 全部正确

## 六、与其他模块的接轨方式

| 接轨点 | 方式 |
|--------|------|
| 输入 | `memory_pipeline.run(text, user_id, agent_id, scene_id, session_id, task_id, db)` |
| 输出 | `PipelineResult` (memory_ids, new/merged/discarded/updated counts, details) |
| 存储 | 直接写入 `t_memory` 表全部字段，与现有 search/list/update/delete API 完全兼容 |
| 配置 | LLM/Embedder 密钥独立配置，不依赖 MCP Server |
| 异常 | 复用现有 `MemoryGenerationError`, `LLMServiceError`, `VectorStoreError` |

## 七、运行方式

### 单元测试
```bash
cd memProject
pytest tests/test_memory_generation.py -v
```

### E2E 演示
```bash
# 基础模式（不需要数据库）
python tests/debug/test_generation_e2e.py basic

# 完整模式（需要 Docker 容器运行）
python tests/debug/test_generation_e2e.py full

# 去重验证
python tests/debug/test_generation_e2e.py dedup
```

### API 调用示例
```bash
curl -X POST http://localhost:8000/api/v1/memory/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "用户喜欢用Python，项目deadline下周五，决定用FastAPI", "user_id": "test_001"}'
```

---

## 八、后续建议

1. **异步执行**：当前 `/generate/async` 为同步占位，建议集成 Celery + Redis 实现真正的后台任务队列
2. **记忆压缩**：随着记忆增长，建议实现周期性记忆摘要压缩（设计文档第五章）
3. **权重调优**：去重决策矩阵的 composite 权重（0.5/0.3/0.2）和阈值可在生产环境中根据实际数据调优
4. **Prompt 迭代**：三个抽取 Prompt 可根据实际输出质量持续迭代优化
