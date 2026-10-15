# Investment Intelligence Pro — local, single-user. See docs/operations/deployment.md.
# Node scripts run with `node --run` (Volta's pnpm uses Node 20 on this machine; see deployment.md).
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin/python
IIP_DATA_DIR ?= $(HOME)/.iip
IIP_PORT ?= 8741
export IIP_DATA_DIR IIP_PORT

.PHONY: help setup build run dev open token-rotate test test-browser check lockcheck audit backup backup-encrypted requirements deploy-check \
	restore-encrypted restore-drill clean

help:            ## Show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

setup:           ## Install pinned backend (uv) and frontend (pnpm) dependencies
	cd $(BACKEND) && uv sync --frozen
	cd $(FRONTEND) && pnpm install --frozen-lockfile

build:           ## Type-check and build the frontend into frontend/dist (served by the backend)
	cd $(FRONTEND) && node --run build

run: build       ## Run the app (production mode) on 127.0.0.1:$(IIP_PORT)
	cd $(BACKEND) && IIP_ENV=prod .venv/bin/python -m iip.api

dev:             ## Backend in dev mode (fixtures allowed) + Vite dev server on :5173
	@echo "Backend: http://127.0.0.1:$(IIP_PORT)  ·  Frontend (HMR): http://127.0.0.1:5173"
	cd $(BACKEND) && IIP_ENV=dev IIP_DEV_ORIGINS=http://127.0.0.1:5173 .venv/bin/python -m iip.api & \
	cd $(FRONTEND) && node --run dev

open:            ## Open the app in your browser with the one-time login link (token stays in the URL fragment)
	@test -f "$(IIP_DATA_DIR)/secrets/access-token" || { echo "Start the app once (make run) to create the token."; exit 1; }
	@open "http://127.0.0.1:$(IIP_PORT)/#login=$$(cat "$(IIP_DATA_DIR)/secrets/access-token")"

token-rotate:    ## Replace the access token (all sessions end at next restart)
	rm -f "$(IIP_DATA_DIR)/secrets/access-token" && echo "Token removed; a new one is created at next start."

test:            ## Backend + frontend tests
	cd $(BACKEND) && .venv/bin/pytest -p no:warnings  # addopts already has -q; a second -q hides the pass count
	cd $(FRONTEND) && node --run test

test-browser: build  ## Real-browser security tests SEC-16/SEC-23 (Playwright + Chromium, ~150 MB on first run)
	cd $(BACKEND) && .venv/bin/playwright install chromium
	cd $(BACKEND) && IIP_BROWSER_TESTS=1 .venv/bin/pytest -p no:warnings -m browser tests/browser

lockcheck:       ## SEC-85: lockfiles in sync with manifests; pnpm supply-chain policy present
	cd $(BACKEND) && uv lock --check
	cd $(FRONTEND) && pnpm install --frozen-lockfile --lockfile-only
	@grep -qE '^onlyBuiltDependencies: \[\]$$' $(FRONTEND)/pnpm-workspace.yaml || { echo "SEC-85: onlyBuiltDependencies must be [] in frontend/pnpm-workspace.yaml"; exit 1; }
	@grep -qE '^minimumReleaseAge: [1-9][0-9]*$$' $(FRONTEND)/pnpm-workspace.yaml || { echo "SEC-85: minimumReleaseAge must be set in frontend/pnpm-workspace.yaml"; exit 1; }
	@echo "lockcheck: OK"

check: test lockcheck  ## Full gate: tests, lockfiles, lint, types, build, dependency audit
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
	cd $(FRONTEND) && node --run typecheck && node --run build
	$(MAKE) audit

audit:           ## Known-vulnerability scan of locked dependencies
	cd $(BACKEND) && uvx --quiet pip-audit --strict -r <(uv export --frozen --no-hashes --no-emit-project) || exit 1
	cd $(FRONTEND) && pnpm audit --prod

backup:          ## Verified online backup of the database into $(IIP_DATA_DIR)/backups
	$(PY) -c "import os,pathlib,datetime as d;from iip.store.db import connect,backup;p=pathlib.Path(os.environ['IIP_DATA_DIR']);print(backup(connect(p/'iip.db'),p/'backups'/f'iip-{d.datetime.now(d.UTC):%Y%m%dT%H%M%SZ}.db'))"

backup-encrypted: ## SEC-83: AES-256-GCM backup (scrypt key from IIP_BACKUP_PASSPHRASE, or prompted) into $(IIP_DATA_DIR)/backups
	$(PY) -m iip.store.encrypted_backup backup --data-dir "$(IIP_DATA_DIR)"

restore-encrypted: ## Decrypt + verify the newest (or BACKUP=…) into a NEW file (or DEST=…); never touches the live DB
	$(PY) -m iip.store.encrypted_backup restore --data-dir "$(IIP_DATA_DIR)" $(if $(BACKUP),--backup "$(BACKUP)") $(if $(DEST),--dest "$(DEST)")

restore-drill:   ## Prove the newest backup restores (REL-40) into a temp file — never touches the live DB
	$(PY) -c "import os,pathlib,tempfile;from iip.store.db import restore,connect,integrity_ok;d=pathlib.Path(os.environ['IIP_DATA_DIR'])/'backups';b=max([*d.glob('iip-*.sqlite3'),*d.glob('iip-*.db')],key=lambda p:p.stat().st_mtime);td=tempfile.TemporaryDirectory();t=pathlib.Path(td.name)/'r.db';restore(b,t);c=connect(t);ok=integrity_ok(c);c.close();td.cleanup();print('restore OK (temp copy deleted)' if ok else 'RESTORE FAILED',b);raise SystemExit(0 if ok else 1)"

requirements:    ## Regenerate requirements.txt (hosted runtime deps) from backend/uv.lock — ADR-0013
	scripts/export-requirements.sh > requirements.txt

deploy-check: build ## Validate the Vercel config, requirements sync and the hosted entrypoint — deploys NOTHING
	$(PY) scripts/deploy_check.py

clean:           ## Remove build artefacts (never touches $(IIP_DATA_DIR))
	rm -rf $(FRONTEND)/dist $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
