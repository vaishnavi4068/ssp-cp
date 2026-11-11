-- name: GetCpUserByUsername :one
SELECT user_id, username, email, display_name, role, password_hash, must_change_password,
       failed_login_attempts, locked_until, password_changed_at, last_login_at, is_active, created_at
FROM idp.cp_users WHERE username = $1;

-- name: UpsertCpUserBootstrap :exec
INSERT INTO idp.cp_users (username, email, display_name, role, password_hash, must_change_password, is_active)
VALUES ($1, $2, $3, $4, $5, true, true)
ON CONFLICT (username) DO UPDATE SET role = EXCLUDED.role, email = EXCLUDED.email, display_name = EXCLUDED.display_name;

-- name: UpdateCpUserLoginSuccess :exec
UPDATE idp.cp_users
SET failed_login_attempts = 0, locked_until = NULL, last_login_at = now()
WHERE username = $1;

-- name: UpdateCpUserLoginFailure :exec
UPDATE idp.cp_users
SET failed_login_attempts = failed_login_attempts + 1,
    locked_until = CASE WHEN failed_login_attempts + 1 >= sqlc.arg(max_attempts)::int
                        THEN now() + (sqlc.arg(lockout_seconds)::int * interval '1 second')
                        ELSE locked_until END
WHERE username = $1;

-- name: UpdateCpUserPassword :exec
UPDATE idp.cp_users
SET password_hash = $2, must_change_password = false, password_changed_at = now()
WHERE username = $1;

-- name: UnlockCpUser :exec
UPDATE idp.cp_users SET failed_login_attempts = 0, locked_until = NULL WHERE username = $1;

-- name: InsertSession :one
INSERT INTO idp.cp_sessions (session_id, username, csrf_token, expires_at)
VALUES ($1, $2, $3, $4)
RETURNING session_id, username, csrf_token, created_at, last_seen_at, expires_at, revoked;

-- name: GetSession :one
SELECT session_id, username, csrf_token, created_at, last_seen_at, expires_at, revoked
FROM idp.cp_sessions WHERE session_id = $1;

-- name: RevokeSession :exec
UPDATE idp.cp_sessions SET revoked = true WHERE session_id = $1;

-- name: TouchSession :exec
UPDATE idp.cp_sessions SET last_seen_at = now() WHERE session_id = $1 AND revoked = false;

-- name: InsertAuditLog :one
INSERT INTO idp.cp_audit_log (
  actor_username, actor_role, source_ip, action_type, resource_id, request_id, approval_id, reason, details
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
RETURNING audit_id, occurred_at, actor_username, actor_role, source_ip, action_type,
          resource_id, request_id, approval_id, reason, details;
