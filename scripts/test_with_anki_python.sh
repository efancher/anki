#!/usr/bin/env bash
# Run addon compatibility tests using Anki's bundled Python (no GUI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${ANKI_PYTHON:-}" ]]; then
  PYTHON="${ANKI_PYTHON}"
elif [[ -x "${HOME}/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13" ]]; then
  PYTHON="${HOME}/Library/Application Support/AnkiProgramFiles/.venv/bin/python3.13"
else
  echo "Set ANKI_PYTHON to Anki's bundled python3.13 (see AnkiProgramFiles/.venv)." >&2
  exit 1
fi

cd "${REPO_ROOT}"
echo "Using Anki Python: ${PYTHON}"

echo "Unit tests (system python)..."
python3 -m pytest tests/test_wk_deck_options.py -q

echo "Anki 25 collection smoke tests..."
"${PYTHON}" tests/test_anki25_collection_compat.py -v
