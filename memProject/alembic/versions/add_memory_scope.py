"""add_memory_scope

Revision ID: a1b2c3d4e5f6
Revises: 9d20e9cb00e2
Create Date: 2026-07-20
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9d20e9cb00e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增列（可空，后续回填后设 NOT NULL）
    op.add_column('t_memory', sa.Column('memory_scope', sa.String(16), nullable=True))
    # 约束
    op.create_check_constraint(
        'ck_memory_scope',
        't_memory',
        "memory_scope IS NULL OR memory_scope IN ('user','session','task','agent')"
    )
    # 索引
    op.create_index('idx_memory_user_status_scope', 't_memory', ['user_id', 'status', 'memory_scope'])
    op.create_index('idx_memory_user_scene_status_scope', 't_memory', ['user_id', 'scene_id', 'status', 'memory_scope'])

    # 历史数据回填
    op.execute("""
        UPDATE t_memory SET memory_scope = CASE
            WHEN task_id IS NOT NULL AND task_id != '' THEN 'task'
            WHEN session_id IS NOT NULL AND session_id != '' THEN 'session'
            ELSE 'user'
        END
        WHERE memory_scope IS NULL
    """)


def downgrade() -> None:
    op.drop_constraint('ck_memory_scope', 't_memory', type_='check')
    op.drop_column('t_memory', 'memory_scope')
    op.drop_index('idx_memory_user_scene_status_scope', table_name='t_memory')
    op.drop_index('idx_memory_user_status_scope', table_name='t_memory')
