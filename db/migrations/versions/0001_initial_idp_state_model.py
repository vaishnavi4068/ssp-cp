"""Initial SPP four-gate data model (`idp` schema, 18 tables + `v_resource_status` view + local auth tables).

Revision ID: 0001_initial_idp_state_model
Revises: None
Create Date: 2026-10-21 17:45:00.000000

Governing Specs:
- ADR-GLB-003 (Four-Gate State Model)
- ADR-GLB-004 (Data Model and Centralized PostgreSQL Database / AlloyDB)
- ADR-GLB-005 (Identity, Workload Identity, and Local Auth)
- ADR-GLB-009 (Resource Kind Registry)
- ADR-BP-003 (Roles, Personas, and Approval Gate Governance)
- specs/data-model/spp_state_model.sql
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "0001_initial_idp_state_model"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load_sql_file() -> str:
    here = Path(__file__).resolve()
    sql_path = here.parents[2] / "spp_state_model.sql"
    raw = sql_path.read_text(encoding="utf-8")
    # Strip explicit BEGIN; and COMMIT; since Alembic manages the transaction.
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped in {"BEGIN;", "COMMIT;"}:
            continue
        lines.append(line)
    return "\n".join(lines)


AUTH_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS idp.cp_users (
  user_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username              text NOT NULL UNIQUE,
  email                 text NOT NULL UNIQUE,
  display_name          text NOT NULL,
  role                  text NOT NULL,
  password_hash         text NOT NULL,
  must_change_password  boolean NOT NULL DEFAULT true,
  failed_login_attempts integer NOT NULL DEFAULT 0,
  locked_until          timestamptz,
  password_changed_at   timestamptz,
  last_login_at         timestamptz,
  is_active             boolean NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS idp.cp_sessions (
  session_id   text PRIMARY KEY,
  username     text NOT NULL REFERENCES idp.cp_users (username),
  csrf_token   text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked      boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS cp_sessions_username_idx ON idp.cp_sessions (username);

CREATE TABLE IF NOT EXISTS idp.cp_audit_log (
  audit_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  occurred_at    timestamptz NOT NULL DEFAULT now(),
  actor_username text NOT NULL,
  actor_role     text NOT NULL,
  source_ip      text NOT NULL DEFAULT '127.0.0.1',
  action_type    text NOT NULL,
  resource_id    uuid,
  request_id     uuid,
  approval_id    uuid,
  reason         text NOT NULL,
  details        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS cp_audit_log_occurred_idx ON idp.cp_audit_log (occurred_at DESC);
"""


def upgrade() -> None:
    bind = op.get_bind()
    raw_conn = bind.connection
    with raw_conn.cursor() as cur:
        cur.execute(_load_sql_file())
        cur.execute(AUTH_TABLES_DDL)


def downgrade() -> None:
    bind = op.get_bind()
    raw_conn = bind.connection
    with raw_conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS idp CASCADE;")
        cur.execute("DROP TABLE IF EXISTS public.alembic_version;")
