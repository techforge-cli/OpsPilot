# Dependencies Log

## Business Dependencies

### Customers
- None yet — starting from scratch

### Design Partners
- None yet — need 2-3 enterprise IT managers before building enterprise features

### Legal Structure
- None yet — need business entity, terms of service, privacy policy

### Pricing
- Not set — anchor at $5K-15K/year for on-prem enterprise (unvalidated)

### Deployment Targets
- Docker Compose on a VM (primary)
- Bare metal / systemd (secondary)

### Licensing Model
- Node-locked license file (HMAC-signed, machine-fingerprint, air-gapped)

### Competitors
- Not researched — need competitive analysis

## Development Dependencies

### Runtime (Python 3.11+, CI uses 3.14)
- fastapi>=0.115 — web framework
- uvicorn>=0.30 — ASGI server
- httpx>=0.27 — HTTP client (Ollama API)
- pydantic>=2.8 — data validation
- pydantic-settings>=2.0 — env-based config
- pyyaml>=6.0 — playbook parsing
- jinja2>=3.1 — HTML templates

### Dev/Test
- pytest>=8.0 — test runner
- pytest-asyncio>=0.24 — async test support
- ruff>=0.8 — linter

### External Services
- Ollama (local LLM, OpenAI-compatible API) — required for analysis
- SQLite (embedded) — primary data store

### Infrastructure
- systemd — service management (bare metal deploy)
- Docker + Docker Compose — containerized deploy

### Security
- HMAC-SHA256 — license signing, session tokens
- bcrypt / argon2 — password hashing (NOT YET IMPLEMENTED)
- TLS — via reverse proxy (NOT YET BUILT IN)

## Phase 2 Build Order
1. Docker Compose deployment
2. Node-locked license file
3. Audit integrity (hash chain + HMAC + fsync)
4. Structured logging + /readyz endpoint
5. SSO/LDAP integration
6. Backup/restore tooling
7. Air-gapped install path

## Status
- [x] Docker Compose deployment
- [x] Node-locked license file
- [x] Audit integrity (hash chain + HMAC + fsync)
- [x] /readyz endpoint
- [ ] SSO/LDAP integration
- [ ] Backup/restore tooling
- [ ] Air-gapped install path
