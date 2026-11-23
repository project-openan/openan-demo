#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_VERSION="24.15.0"
WORK_DIR="$HOME/.cache/ontology-demo-linux-build"

if [ -s "$HOME/.nvm/nvm.sh" ]; then
  source "$HOME/.nvm/nvm.sh"
fi

if ! command -v nvm >/dev/null 2>&1; then
  echo "nvm is not installed. Run the nvm installation first."
  exit 1
fi

nvm use "$NODE_VERSION" >/dev/null
if [ "$(node -p 'process.arch')" != "x64" ]; then
  echo "Expected x64 Node.js, got: $(node -p 'process.arch')"
  exit 1
fi

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/server" "$WORK_DIR/build"
cp "$PROJECT_ROOT"/server/*.js "$WORK_DIR/server/"

cd "$WORK_DIR"
if [ ! -x node_modules/.bin/esbuild ] || [ ! -x node_modules/.bin/postject ]; then
  npm install --no-save --package-lock=false esbuild postject
fi

node_modules/.bin/esbuild server/index.js \
  --bundle \
  --platform=node \
  --format=cjs \
  --outfile=build/server.cjs

cat > sea-config.json <<'JSON'
{
  "main": "build/server.cjs",
  "output": "build/sea-prep.blob",
  "disableExperimentalSEAWarning": true,
  "useCodeCache": false,
  "useSnapshot": false
}
JSON

node --experimental-sea-config sea-config.json
cp "$(command -v node)" build/ontology-api
node_modules/.bin/postject build/ontology-api \
  NODE_SEA_BLOB \
  build/sea-prep.blob \
  --sentinel-fuse NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2
chmod +x build/ontology-api

mkdir -p "$PROJECT_ROOT/build"
cp build/ontology-api "$PROJECT_ROOT/build/ontology-api"

printf '\nBuild completed:\n'
file "$PROJECT_ROOT/build/ontology-api"
ls -lh "$PROJECT_ROOT/build/ontology-api"
