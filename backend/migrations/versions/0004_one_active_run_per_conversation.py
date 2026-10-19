"""one active analysis run per conversation

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 18:30:00.000000+00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Migrations run before the server starts, so any active run is left over from a stopped
    # process (restart recovery would fail it anyway). Fail all but the newest per conversation
    # so the unique index can be built.
    op.execute(
        """
        UPDATE analysis_runs
        SET status = 'failed',
            stop_reason = 'error',
            error_code = 'interrupted',
            error_message = 'The analysis was interrupted by a server restart. Ask again.',
            finished_at = now()
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY conversation_id ORDER BY created_at DESC, id DESC
                ) AS position
                FROM analysis_runs
                WHERE status IN ('queued', 'running')
            ) AS active
            WHERE position > 1
        )
        """
    )
    op.create_index(
        "uq_analysis_runs_conversation_id_active",
        "analysis_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_analysis_runs_conversation_id_active",
        table_name="analysis_runs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
