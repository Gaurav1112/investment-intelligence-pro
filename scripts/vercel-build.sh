#!/usr/bin/env bash
# Vercel build step for the hosted mode (ADR-0013, WP A04): build the frontend into frontend/dist, then publish it to
# public/, which Vercel serves from its CDN without waking the Python function (vercel.json carries the same security
# headers as the app, plus `immutable` caching for the hashed files under /assets/). The function keeps
# frontend/dist as a fallback. Same pinned lockfile and pnpm policy as `make setup` (frozen lockfile, no dependency
# build scripts, minimumReleaseAge). Runs on Vercel's build image, not locally.
#
#   --publish-only   skip install/build; only copy an existing frontend/dist to public/ (used by the tests).
#   IIP_BUILD_ROOT   repository root to operate on (default: this script's parent directory; tests use a temp dir).
set -euo pipefail
root="${IIP_BUILD_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

if [[ "${1:-}" != "--publish-only" ]]; then
  cd "$root/frontend"
  npx --yes pnpm@10.28.2 install --frozen-lockfile
  node --run build
fi

dist="$root/frontend/dist"
test -f "$dist/index.html" || { echo "vercel-build: $dist/index.html missing" >&2; exit 1; }
rm -rf "$root/public"
mkdir "$root/public"
cp -R "$dist/." "$root/public/"
test -f "$root/public/index.html"
echo "vercel-build: published $(find "$root/public" -type f | wc -l | tr -d ' ') file(s) to public/"
