# Investment Intelligence Pro — local, single-user. See docs/operations/deployment.md.
# Node scripts run with `node --run` (Volta's pnpm uses Node 20 on this machine; see deployment.md).
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend
PY := $(BACKEND)/.venv/bin/python
IIP_DATA_DIR ?= $(HOME)/.iip
IIP_PORT ?= 8741
export IIP_DATA_DIR IIP_PORT

.PHONY: help setup build run dev open token-rotate test check audit backup restore-drill clean

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
	cd $(BACKEND) && .venv/bin/pytest -q -p no:warnings
	cd $(FRONTEND) && node --run test

check: test      ## Full gate: tests, lint, types, build, dependency audit
	cd $(BACKEND) && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy
	cd $(FRONTEND) && node --run typecheck && node --run build
	$(MAKE) audit

audit:           ## Known-vulnerability scan of locked dependencies
	cd $(BACKEND) && uvx --quiet pip-audit --strict -r <(uv export --frozen --no-hashes --no-emit-project) || exit 1
	cd $(FRONTEND) && pnpm audit --prod

backup:          ## Verified online backup of the database into $(IIP_DATA_DIR)/backups
	$(PY) -c "import os,pathlib,datetime as d;from iip.store.db import connect,backup;p=pathlib.Path(os.environ['IIP_DATA_DIR']);print(backup(connect(p/'iip.db'),p/'backups'/f'iip-{d.datetime.now(d.UTC):%Y%m%dT%H%M%SZ}.db'))"

restore-drill:   ## Prove the newest backup restores (REL-40) into a temp file — never touches the live DB
	$(PY) -c "import os,pathlib,tempfile;from iip.store.db import restore,connect,integrity_ok;b=sorted((pathlib.Path(os.environ['IIP_DATA_DIR'])/'backups').glob('*.db'))[-1];t=pathlib.Path(tempfile.mkdtemp())/'r.db';restore(b,t);print('restore OK' if integrity_ok(connect(t)) else 'RESTORE FAILED',b)"

clean:           ## Remove build artefacts (never touches $(IIP_DATA_DIR))
	rm -rf $(FRONTEND)/dist $(BACKEND)/.pytest_cache $(BACKEND)/.mypy_cache $(BACKEND)/.ruff_cache
