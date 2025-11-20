# Security policy

## Supported version

Security fixes are applied to the latest `main` revision of this repository.

## Reporting a vulnerability

Do not publish credentials, exploit payloads, private data or a proof of concept in a public issue. Contact the repository maintainer privately through the security contact configured for the fork, with a concise reproduction, affected paths and impact. If no private contact is configured, open a minimal public issue asking for a secure contact without disclosing the exploit.

## Security model

Task agents should be treated as untrusted code. Harbor separate verifier mode transfers only explicit artifacts. Verifiers must not import or execute agent-controlled source. Docker tasks run non-root where practical, no task requires privileged Docker, and local cleanup refuses paths outside the suite root. API keys belong only in environment variables or ignored local configuration.
