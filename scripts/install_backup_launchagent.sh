#!/usr/bin/env bash
# Install or remove a launchd agent that runs backup_to_google_drive.sh weekly.
#
# Usage:
#   ./scripts/install_backup_launchagent.sh install
#   ./scripts/install_backup_launchagent.sh uninstall
#   ./scripts/install_backup_launchagent.sh status
#
# Schedule: Sundays at 2:15 AM (edit START_* constants below to change).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/backup_to_google_drive.sh"
LABEL="local.anki.google-drive-backup"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LAUNCHD_TARGET="gui/$(id -u)"
LOG_DIR="${HOME}/Library/Logs/anki-backup"

# StartCalendarInterval — Weekday 0 and 7 = Sunday (launchd).
START_WEEKDAY=0
START_HOUR=2
START_MINUTE=15

usage() {
  cat <<EOF
Usage: $(basename "$0") install|uninstall|status

  install     Write LaunchAgent plist and load it (weekly backup)
  uninstall   Unload and remove the LaunchAgent
  status      Show whether the agent is loaded

Backup script: ${BACKUP_SCRIPT}
Plist path:    ${PLIST_PATH}
Schedule:      Sunday ${START_HOUR}:$(printf '%02d' "${START_MINUTE}") (local time)
EOF
}

require_backup_script() {
  if [[ ! -x "$BACKUP_SCRIPT" ]]; then
    echo "Backup script not found or not executable: $BACKUP_SCRIPT" >&2
    exit 1
  fi
}

write_plist() {
  mkdir -p "$LOG_DIR"
  cat >"$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${BACKUP_SCRIPT}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>${START_WEEKDAY}</integer>
    <key>Hour</key>
    <integer>${START_HOUR}</integer>
    <key>Minute</key>
    <integer>${START_MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/backup.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/backup.stderr.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF
  echo "Wrote ${PLIST_PATH}"
}

unload_agent() {
  launchctl bootout "${LAUNCHD_TARGET}/${LABEL}" 2>/dev/null || \
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
}

load_agent() {
  unload_agent
  if launchctl bootstrap "${LAUNCHD_TARGET}" "$PLIST_PATH" 2>/dev/null; then
    launchctl enable "${LAUNCHD_TARGET}/${LABEL}" 2>/dev/null || true
  else
    launchctl load "$PLIST_PATH"
  fi
}

cmd_install() {
  require_backup_script
  write_plist
  load_agent
  echo "LaunchAgent installed. Next run: Sunday ${START_HOUR}:$(printf '%02d' "${START_MINUTE}") (if Mac is awake)."
  echo "Launchd logs: ${LOG_DIR}/"
  echo "Backup log (on Drive): Google Drive/My Drive/anki/backup.log"
  echo ""
  echo "Test now: ${BACKUP_SCRIPT} --dry-run"
  echo "Run once:  ${BACKUP_SCRIPT}"
}

cmd_uninstall() {
  unload_agent
  rm -f "$PLIST_PATH"
  echo "Removed ${PLIST_PATH}"
}

cmd_status() {
  if [[ -f "$PLIST_PATH" ]]; then
    echo "Plist: present (${PLIST_PATH})"
  else
    echo "Plist: not installed"
  fi
  if launchctl print "${LAUNCHD_TARGET}/${LABEL}" &>/dev/null; then
    echo "Agent: loaded"
    launchctl print "${LAUNCHD_TARGET}/${LABEL}" 2>/dev/null | grep -E 'state =|path =|last exit|runs =' || true
  else
    echo "Agent: not loaded"
  fi
}

main() {
  local command="${1:-}"
  case "$command" in
    install) cmd_install ;;
    uninstall) cmd_uninstall ;;
    status) cmd_status ;;
    -h | --help | "")
      usage
      [[ -n "$command" ]] || exit 0
      ;;
    *)
      echo "Unknown command: $command" >&2
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
