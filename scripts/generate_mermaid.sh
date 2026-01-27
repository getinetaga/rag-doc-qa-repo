#!/usr/bin/env bash
# Generate SVG and PNG for all .mmd files under docs/diagrams
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIAG_DIR="$ROOT_DIR/docs/diagrams"
OUT_DIR="$ROOT_DIR/docs/assets/diagrams"
mkdir -p "$OUT_DIR"
for f in "$DIAG_DIR"/*.mmd; do
  [ -f "$f" ] || continue
  base=$(basename "$f" .mmd)
  echo "Rendering $base"
  mmdc -i "$f" -o "$OUT_DIR/$base.svg" || true
  mmdc -i "$f" -o "$OUT_DIR/$base.png" || true
done
echo "Done. Output in $OUT_DIR"
