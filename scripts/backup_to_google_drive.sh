#!/usr/bin/env bash
# Back up the anki generator repo and Anki profile to Google Drive (My Drive/anki/).
#
# Usage:
#   ./scripts/backup_to_google_drive.sh
#   ./scripts/backup_to_google_drive.sh --dry-run
#
# Environment overrides:
#   GOOGLE_DRIVE_ROOT   — e.g. "$HOME/Google Drive/My Drive" (auto-detected if unset)
#   ANKI_PROFILE_DIR    — default: ~/Library/Application Support/Anki2/User 1
#   BACKUP_RETENTION_DAYS — delete dated backups older than this (default: 14, 0 = keep all)
#
# Scheduled backup (recommended on macOS):
#   ./scripts/install_backup_launchagent.sh install
#   ./scripts/install_backup_launchagent.sh status
#   ./scripts/install_backup_launchagent.sh uninstall

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRY_RUN=0
FORCE=0
REPO_ONLY=0
ANKI_ONLY=0
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

usage() {
  sed -n '2,20p' "$0"
  echo ""
  echo "Options:"
  echo "  --dry-run       Print rsync commands without copying"
  echo "  --force         Continue even if Anki appears to be running"
  echo "  --repo-only     Skip Anki profile"
  echo "  --anki-only     Skip generator repo"
  echo "  -h, --help      Show this help"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    --repo-only) REPO_ONLY=1 ;;
    --anki-only) ANKI_ONLY=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$REPO_ONLY" -eq 1 && "$ANKI_ONLY" -eq 1 ]]; then
  echo "Cannot use --repo-only and --anki-only together." >&2
  exit 2
fi

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

resolve_google_drive_root() {
  if [[ -n "${GOOGLE_DRIVE_ROOT:-}" ]]; then
    if [[ -d "$GOOGLE_DRIVE_ROOT" ]]; then
      printf '%s\n' "$GOOGLE_DRIVE_ROOT"
      return 0
    fi
    echo "GOOGLE_DRIVE_ROOT is set but not a directory: $GOOGLE_DRIVE_ROOT" >&2
    return 1
  fi

  local candidate
  for candidate in \
    "$HOME/Google Drive/My Drive" \
    "$HOME/Library/CloudStorage/GoogleDrive-"*"/My Drive"; do
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "Google Drive My Drive folder not found. Install Google Drive for Desktop or set GOOGLE_DRIVE_ROOT." >&2
  return 1
}

anki_profile_dir() {
  if [[ -n "${ANKI_PROFILE_DIR:-}" ]]; then
    printf '%s\n' "$ANKI_PROFILE_DIR"
    return 0
  fi
  printf '%s\n' "$HOME/Library/Application Support/Anki2/User 1"
}

anki_is_running() {
  # Anki 2.1.x macOS process name is typically "Anki".
  pgrep -qx Anki 2>/dev/null || pgrep -qx anki 2>/dev/null
}

run_rsync() {
  local label="$1"
  shift
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "[dry-run] rsync $label: $*"
    return 0
  fi
  log "rsync $label..."
  rsync "$@"
}

GOOGLE_DRIVE_ROOT="$(resolve_google_drive_root)"
BACKUP_ROOT="${GOOGLE_DRIVE_ROOT}/anki/backups"
BACKUP_DATE="$(date '+%Y-%m-%d')"
DEST="${BACKUP_ROOT}/${BACKUP_DATE}"
LOG_FILE="${GOOGLE_DRIVE_ROOT}/anki/backup.log"

if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$DEST"
fi

log_to_file() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    log "$@"
  else
    log "$@" | tee -a "$LOG_FILE"
  fi
}

log_to_file "Backup destination: $DEST"

if [[ "$ANKI_ONLY" -eq 0 ]]; then
  log_to_file "Repo: $REPO_ROOT"
fi

if [[ "$REPO_ONLY" -eq 0 ]]; then
  PROFILE="$(anki_profile_dir)"
  log_to_file "Anki profile: $PROFILE"
  if [[ ! -d "$PROFILE" ]]; then
    echo "Anki profile directory not found: $PROFILE" >&2
    exit 1
  fi
  if anki_is_running && [[ "$FORCE" -eq 0 ]]; then
    echo "Anki is running. Quit Anki before backup, or pass --force." >&2
    exit 1
  fi
fi

RSYNC_EXCLUDES=(
  --exclude 'env_anki/'
  --exclude 'venv/'
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '.pytest_cache/'
  --exclude '.DS_Store'
  --exclude 'gen_all.sh'
)

if [[ "$ANKI_ONLY" -eq 0 ]]; then
  run_rsync repo \
    -a \
    "${RSYNC_EXCLUDES[@]}" \
    "$REPO_ROOT/" \
    "$DEST/anki-repo/"
fi

if [[ "$REPO_ONLY" -eq 0 ]]; then
  run_rsync anki-profile \
    -a \
    "$PROFILE/" \
    "$DEST/anki-profile/"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  ln -sfn "$BACKUP_DATE" "${BACKUP_ROOT}/latest"
  log_to_file "Updated symlink: ${BACKUP_ROOT}/latest -> ${BACKUP_DATE}"
fi

if [[ "$BACKUP_RETENTION_DAYS" -gt 0 && "$DRY_RUN" -eq 0 ]]; then
  log_to_file "Pruning backups older than ${BACKUP_RETENTION_DAYS} days..."
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' -mtime "+${BACKUP_RETENTION_DAYS}" -print -exec rm -rf {} +
fi

log_to_file "Backup complete."
