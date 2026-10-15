# Vendored review agents (project-scoped)

Source: https://github.com/affaan-m/ECC (MIT), pinned to commit `b92f181b3b748d1abbc2afd94af6aa7d8c8fca29` (fetched 2026-10-15). Its licence text is in `LICENSE-ECC` (it must stay with these files).
Only these 8 read-only review roles were adopted. ECC's installer, hooks, MCP configs and global rules were deliberately
NOT installed: hooks would run automatically in every Claude Code session on this machine (all projects).

Project rules that override these definitions when they are used here:
- Do not run `npx`, `npm install`, or any command that downloads code; use the project's own gates
  (`make check`, `make audit`, ruff, mypy, tsc, vitest).
- Read-only: report findings with file:line and a reproduction; do not edit code.
- Real-money app: see docs/product/requirements.md §3.6a and docs/architecture/implementation-rules.md.

To update: re-fetch from a reviewed ECC commit and update the pin above.
