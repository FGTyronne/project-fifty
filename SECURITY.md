# Security Policy

Project Fifty is a public repository for an autonomous trading experiment. Treat all published material as permanently public and copyable.

## Never commit secrets

Do not commit:

- broker API keys or secrets;
- model/API credentials;
- database passwords;
- cloud provider credentials;
- private SSH/TLS keys;
- account recovery material;
- live account identifiers where disclosure increases operational risk;
- private webhook URLs;
- secret-manager values or other sensitive operational configuration.

Use runtime environment variables or approved secret-management systems. `.env` files containing real values must remain local and ignored.

## Privilege separation

The intelligence/agent layer must not hold live broker credentials. Live trading credentials belong only to the execution service/runtime that enforces the deterministic risk gateway.

External research and market content must be treated as untrusted input and must not be able to alter permissions, configuration, secrets or execution authority.

## Live and paper separation

Paper and live credentials must be distinct. Live credentials must never be used in tests, examples, CI or development environments.

## Vulnerability reporting

Until a dedicated private reporting channel is configured, do not publish exploit details that could compromise a live deployment. Repository issues may be used for non-sensitive engineering/security observations only.

## Dependency and supply-chain policy

Keep the initial dependency surface small. Pin/lock dependencies, review dependency changes, and use automated security/dependency scanning where available.

## Incident principle

If broker state, credential integrity or internal portfolio state is uncertain, the safe response is to prevent new exposure and reconcile rather than guessing or blindly retrying.
