"""Security: principal identity established from validated Entra token claims.

`principal_identity` is the single entry point. It refuses caller-supplied
identity fields before it reads the claims, validates the claims against the
configured home tenant, and only then resolves or creates the durable
`identity.user_accounts` row. The ordering is deliberate: a request that
smuggles a `principal_id` is rejected even when its token is valid, so the
token is the only identity input that can ever reach persistence.
"""
