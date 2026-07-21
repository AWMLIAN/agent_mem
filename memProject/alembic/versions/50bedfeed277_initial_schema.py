"""initial schema (stub — project scaffolding created tables externally)

Revision ID: 50bedfeed277
Revises:
Create Date: 2026-07-01

WARNING: This is a stub. The actual 12 base tables (t_user, t_agent, etc.)
were created by the project scaffold, not by Alembic. This stub exists only
to satisfy the revision chain referenced by migration 52c1d1f2e3a4.
"""
from alembic import op
import sqlalchemy as sa

revision = "50bedfeed277"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
