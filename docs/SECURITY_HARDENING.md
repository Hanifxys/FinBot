# Security Hardening Migration Plan

## Token Revocation
1. Add endpoint `POST /auth/revoke` with bearer-protected access.
2. Store revoked token fingerprint in Redis key:
   - `auth:revoked:{sha256(token)[:32]}`
   - TTL = remaining token expiry.
3. Enforce revocation check in auth dependency before signature accept.
4. Disable static admin backdoor by default (`ALLOW_ADMIN_BACKDOOR=false`).

## Audit Logging
- Standar audit event untuk admin API:
  - actor
  - target
  - action
  - action_type
  - reason
  - timestamp
- Implementasi awal:
  - token revocation action (`auth_revoke_token`).
- Next: enforce wrapper untuk seluruh `/admin/*` mutating routes.

## Security Test Suite
- `tests/test_security_monitor.py`
  - backdoor disabled by default
  - revoke endpoint creates audit trail
- Tambahan berikutnya:
  - replay revoked token
  - privilege escalation matrix
  - rate-limit bypass scenarios
