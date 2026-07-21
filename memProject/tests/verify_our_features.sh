#!/bin/bash
# 验证"通用记忆建模与多层记忆管理"功能
# 用法: bash verify_our_features.sh <服务器IP>

IP=${1:-localhost}
PORT=8000
BASE="http://${IP}:${PORT}/api/v1"

echo "=========================================="
echo "  验证: 类型感知写入 + 多层聚合"
echo "  服务器: $BASE"
echo "=========================================="

# 注册 Agent
echo -e "\n【注册】"
RESP=$(curl -s -X POST $BASE/agent/register \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"verify_our","scene_id":"v","permissions":[]}')
KEY=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['api_key'])")
H="-H X-API-Key:$KEY -H X-User-Id:test_u -H Content-Type:application/json"

echo "Agent: OK"

# ─── 功能1: 偏好替换 ───
echo -e "\n【功能1: 偏好新旧替换】"
echo "写入偏好A: 喜欢Vim编辑器"
curl -s -X POST $BASE/memory/write $H \
  -d '{"user_id":"test_u","interaction_type":"dialogue","messages":[{"role":"user","content":"我喜欢用Vim编辑器"}]}' > /dev/null

echo "写入偏好B: 改用VS Code"
curl -s -X POST $BASE/memory/write $H \
  -d '{"user_id":"test_u","interaction_type":"dialogue","messages":[{"role":"user","content":"我现在改用VS Code了"}]}' > /dev/null

echo "验证: 查看数据库偏好状态"
ssh $IP "docker exec mem-postgres psql -U memuser -d agent_memory -c \"
  SELECT status, LEFT(content,50) FROM t_memory
  WHERE user_id='test_u' AND memory_type='preference'
  ORDER BY updated_at DESC LIMIT 3;
\"" 2>/dev/null || \
docker exec mem-postgres psql -U memuser -d agent_memory -c \
  "SELECT status, LEFT(content,50) FROM t_memory
   WHERE user_id='test_u' AND memory_type='preference'
   ORDER BY updated_at DESC LIMIT 3;"

echo "预期: 最新一条(VS Code)为active, 旧一条(Vim)为pending_update"

# ─── 功能2: 事实冲突 ───
echo -e "\n【功能2: 事实冲突检测】"
echo "写入事实A: 数据库地址"
curl -s -X POST $BASE/memory/write $H \
  -d '{"user_id":"test_u","interaction_type":"dialogue","messages":[{"role":"user","content":"公司数据库 pg.example.com:5432"}]}' > /dev/null

echo "写入事实B: 相似的数据库地址"
curl -s -X POST $BASE/memory/write $H \
  -d '{"user_id":"test_u","interaction_type":"dialogue","messages":[{"role":"user","content":"数据库连接 pg.example.com:5432"}]}' > /dev/null

echo "验证: 查看数据库事实冲突"
docker exec mem-postgres psql -U memuser -d agent_memory -c \
  "SELECT status, LEFT(content,50) FROM t_memory
   WHERE user_id='test_u' AND memory_type='fact'
   ORDER BY updated_at DESC LIMIT 3;" 2>/dev/null

echo "预期: 高度相似的事实被标为conflict"

# ─── 功能3: 三层聚合 ───
echo -e "\n【功能3: 多层聚合】"

echo "用户画像 (user级):"
curl -s -X POST $BASE/memory/context $H \
  -d '{"query":"测试","user_id":"test_u","include_preferences":true,"include_facts":true}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'  fragments: {d[\"memory_count\"]}')" 2>/dev/null

echo "会话上下文 (session级):"
curl -s -X POST $BASE/memory/context $H \
  -d '{"query":"测试","user_id":"test_u","session_id":"v1"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'  fragments: {d[\"memory_count\"]}')" 2>/dev/null

echo "预期: 不同层级返回不同维度的聚合结果"

# ─── 功能4: 软删除自动清理 ───
echo -e "\n【功能4: 软删除自动清理14天】"
echo "注意: 每次软删除自动附带清理超过14天的已删记忆"
