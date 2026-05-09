"""Add rule engine tables and columns

Revision ID: c4e2f5d8a1b2
Revises: 8ad3f4433f0d
Create Date: 2026-04-10 00:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e2f5d8a1b2"
down_revision = "8ad3f4433f0d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("rule_key", sa.String(length=120), nullable=True))
    op.add_column("alert_rules", sa.Column("rule_type", sa.String(length=120), nullable=True))
    op.add_column("alert_rules", sa.Column("action", sa.JSON(), nullable=True))

    op.create_index("ix_alert_rules_rule_key", "alert_rules", ["rule_key"], unique=False)
    op.create_index("ix_alert_rules_rule_type", "alert_rules", ["rule_type"], unique=False)
    op.create_index("ix_alert_rules_tenant_rule_key", "alert_rules", ["tenant_id", "rule_key"], unique=True)

    op.create_table(
        "alert_rule_conditions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rule_conditions_rule_id", "alert_rule_conditions", ["rule_id"], unique=False)
    op.create_index("ix_alert_rule_conditions_key", "alert_rule_conditions", ["key"], unique=False)
    op.create_index(
        "ix_alert_rule_conditions_rule_key",
        "alert_rule_conditions",
        ["rule_id", "key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_alert_rule_conditions_rule_key", table_name="alert_rule_conditions")
    op.drop_index("ix_alert_rule_conditions_key", table_name="alert_rule_conditions")
    op.drop_index("ix_alert_rule_conditions_rule_id", table_name="alert_rule_conditions")
    op.drop_table("alert_rule_conditions")

    op.drop_index("ix_alert_rules_tenant_rule_key", table_name="alert_rules")
    op.drop_index("ix_alert_rules_rule_type", table_name="alert_rules")
    op.drop_index("ix_alert_rules_rule_key", table_name="alert_rules")
    op.drop_column("alert_rules", "action")
    op.drop_column("alert_rules", "rule_type")
    op.drop_column("alert_rules", "rule_key")
