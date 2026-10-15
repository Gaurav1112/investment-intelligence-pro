#!/usr/bin/env bash
# Vercel build step for the hosted mode (ADR-0013): build the frontend into frontend/dist, which the Python function
# serves with the same CSP and security headers as locally. Same pinned lockfile and pnpm policy as `make setup`
# (frozen lockfile, no dependency build scripts, minimumReleaseAge). Runs on Vercel's build image, not locally.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npx --yes pnpm@10.28.2 install --frozen-lockfile
node --run build
test -f dist/index.html
