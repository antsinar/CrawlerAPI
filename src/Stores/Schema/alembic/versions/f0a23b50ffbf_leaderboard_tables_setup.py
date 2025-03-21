"""Leaderboard tables setup

Revision ID: f0a23b50ffbf
Revises:
Create Date: 2025-03-11 01:14:42.827352

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0a23b50ffbf"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "leaderboard",
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("course_url", sa.String(length=100), nullable=False),
        sa.Column("moves", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("uid"),
    )
    op.create_table(
        "leaderboard_tracker",
        sa.Column("uid", sa.String(), nullable=False),
        sa.Column("data", sa.String(length=500), nullable=False),
        sa.PrimaryKeyConstraint("uid"),
    )
    op.create_table(
        "leaderboard_display",
        sa.Column("uid", sa.String(), nullable=False),
        sa.Column("course_uid", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(precision=3), nullable=False),
        sa.Column("nickname", sa.String(length=10), nullable=False),
        sa.Column(
            "stamp",
            sa.String(length=40),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("leaderboard_uid", sa.Integer(), nullable=False),
        sa.Column("tracker_uid", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["leaderboard_uid"],
            ["leaderboard.uid"],
        ),
        sa.ForeignKeyConstraint(
            ["tracker_uid"],
            ["leaderboard_tracker.uid"],
        ),
        sa.PrimaryKeyConstraint("uid"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("leaderboard_display")
    op.drop_table("leaderboard_tracker")
    op.drop_table("leaderboard")
    # ### end Alembic commands ###
