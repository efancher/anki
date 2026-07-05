#!/usr/bin/env bash
# Copy WK Anki add-ons from this repo into Anki's add-ons folder.
#
# Usage:
#   ./scripts/sync_anki_addons.sh           # sync (macOS default target)
#   ./scripts/sync_anki_addons.sh --dry-run # print actions only
#
# Override target:
#   ANKI_ADDONS_DIR="$HOME/Library/Application Support/Anki2/addons21" ./scripts/sync_anki_addons.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ADDON_SRC="${REPO_ROOT}/anki_addon"
DRY_RUN=0

WK_ADDONS=(
  wk_deck_options
  wk_filtered_decks
  wk_unlock
  wk_adaptive_new
  wk_health_check
  wk_immersion
)

# Retired add-ons — remove if still present (old wk_mining breaks Anki 25+ mining hooks).
DEPRECATED_ADDONS=(
  wk_mining
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run]

  Sync anki_addon/{wk_deck_options,wk_filtered_decks,wk_unlock,wk_adaptive_new,wk_health_check,wk_immersion}
  into Anki's add-ons directory (rsync, removes stale files).
  Removes deprecated wk_mining if present (superseded by wk_immersion).

  Set ANKI_ADDONS_DIR to override the destination.
EOF
}

resolve_addons_dir() {
  if [[ -n "${ANKI_ADDONS_DIR:-}" ]]; then
    printf '%s\n' "${ANKI_ADDONS_DIR}"
    return
  fi
  case "$(uname -s)" in
    Darwin)
      printf '%s\n' "${HOME}/Library/Application Support/Anki2/addons21"
      ;;
    Linux)
      printf '%s\n' "${HOME}/.local/share/Anki2/addons21"
      ;;
    MINGW* | MSYS* | CYGWIN*)
      if [[ -n "${APPDATA:-}" ]]; then
        printf '%s\n' "${APPDATA}/Anki2/addons21"
      else
        return 1
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

cleanup_dest() {
  local dest="$1"
  local addon_name="$2"
  rm -rf "${dest}/__pycache__"
  # Bad manual install: cp -R wk_foo "$ADDONS/" when wk_foo/ already exists.
  if [[ -d "${dest}/${addon_name}" ]]; then
    rm -rf "${dest}/${addon_name}"
  fi
}

sync_addon() {
  local name="$1"
  local src="${ADDON_SRC}/${name}"
  local dest="${ADDONS_DIR}/${name}"

  if [[ ! -d "${src}" ]]; then
    echo "skip: source missing (${src})" >&2
    return 0
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "would sync: ${src}/ -> ${dest}/"
    return 0
  fi

  mkdir -p "${dest}"
  rsync -a --delete \
    --exclude '__pycache__/' \
    --exclude '.DS_Store' \
    "${src}/" "${dest}/"
  cleanup_dest "${dest}" "${name}"
  echo "synced: ${name} -> ${dest}"
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
  done

  if ! ADDONS_DIR="$(resolve_addons_dir)"; then
    echo "Could not resolve Anki add-ons directory; set ANKI_ADDONS_DIR." >&2
    exit 1
  fi

  if [[ ! -d "${ADDONS_DIR}" ]]; then
    echo "Anki add-ons directory not found: ${ADDONS_DIR}" >&2
    echo "Install Anki once, or create the directory, then retry." >&2
    exit 1
  fi

  for name in "${WK_ADDONS[@]}"; do
    sync_addon "${name}"
  done

  for name in "${DEPRECATED_ADDONS[@]}"; do
    dest="${ADDONS_DIR}/${name}"
    if [[ ! -d "${dest}" ]]; then
      continue
    fi
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      echo "would remove deprecated add-on: ${dest}/"
    else
      rm -rf "${dest}"
      echo "removed deprecated add-on: ${name} (use wk_immersion instead)"
    fi
  done

  if [[ "${DRY_RUN}" -eq 0 ]]; then
    echo ""
    echo "Restart Anki to load updated add-on code."
  fi
}

main "$@"
