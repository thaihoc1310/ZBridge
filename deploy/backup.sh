#!/usr/bin/env bash
# Backs up what cannot be rebuilt from the repository:
#   - the Postgres database (customers, debts, automations, users)
#   - the encrypted Zalo session (losing it only costs a QR re-scan)
#
# Everything is compressed, optionally encrypted, then optionally pushed to any
# S3-compatible bucket via rclone (Cloudflare R2, Backblaze B2, AWS S3, ...).
# A failure alerts Telegram through the running backend: a backup that quietly
# stopped working is worse than no backup at all.
#
# Usage:  ./deploy/backup.sh [destination-dir]
# Cron:   0 */6 * * * cd /opt/zbridge && ./deploy/backup.sh >> /var/log/zbridge-backup.log 2>&1
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
DEST="${1:-${BACKUP_DIR:-./backups}}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
# Anything smaller means pg_dump failed rather than produced a small database.
MIN_DUMP_BYTES="${MIN_DUMP_BYTES:-2000}"

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }
log() { echo "[$(date -Is)] $*"; }

read_env() {
  local key="$1" fallback="${2:-}"
  local value
  value="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  echo "${value:-$fallback}"
}

# Report through the backend so the alert path (dedup, Telegram) is the same one
# the application uses. Never let alerting failures mask the backup failure.
notify_failure() {
  local message="$1"
  compose exec -T backend python - "$message" <<'PY' || true
import json, os, sys, urllib.request
payload = json.dumps({
    "code": "BACKUP_FAILED",
    "message": sys.argv[1],
    "severity": "CRITICAL",
    "context": {"Nguồn": "deploy/backup.sh"},
}).encode()
request = urllib.request.Request(
    "http://localhost:8000/internal/zalo/alerts",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "X-Zalo-Event-Secret": os.environ["ZALO_EVENT_SECRET"],
    },
)
urllib.request.urlopen(request, timeout=10)
PY
}

fail() {
  log "FAILED: $*"
  notify_failure "Backup thất bại: $*"
  exit 1
}

DB_USER="$(read_env POSTGRES_USER zbridge)"
DB_NAME="$(read_env POSTGRES_DB zbridge)"
PASSPHRASE="${BACKUP_PASSPHRASE:-$(read_env BACKUP_PASSPHRASE)}"
REMOTE="${BACKUP_REMOTE:-$(read_env BACKUP_REMOTE)}"

mkdir -p "$DEST"
DEST_ABS="$(cd "$DEST" && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
SUFFIX=""

if [ -n "$PASSPHRASE" ]; then
  command -v gpg >/dev/null || fail "BACKUP_PASSPHRASE được đặt nhưng không có gpg trên máy"
  SUFFIX=".gpg"
  encrypt() { gpg --batch --quiet --symmetric --cipher-algo AES256 \
                  --passphrase-fd 3 --output "$1" 3<<<"$PASSPHRASE"; }
else
  log "WARNING: BACKUP_PASSPHRASE trống — backup sẽ KHÔNG được mã hoá"
  encrypt() { cat > "$1"; }
fi

# ── Database ─────────────────────────────────────────────────────────────────
DUMP="$DEST_ABS/postgres-$STAMP.sql.gz$SUFFIX"
log "dumping database $DB_NAME"
compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip | encrypt "$DUMP" \
  || fail "pg_dump không chạy được"

SIZE="$(stat -c %s "$DUMP")"
[ "$SIZE" -ge "$MIN_DUMP_BYTES" ] || { rm -f "$DUMP"; fail "dump chỉ có ${SIZE} bytes, nghi ngờ lỗi"; }
log "database dump ok (${SIZE} bytes)"

# ── Zalo session ─────────────────────────────────────────────────────────────
# Read it through the gateway service so the compose volume prefix never has to
# be guessed.
SESSION="$DEST_ABS/zalo-session-$STAMP.tgz$SUFFIX"
if compose run --rm --no-deps -T zalo-gateway \
     tar czf - -C /data/zalo-session . 2>/dev/null | encrypt "$SESSION"; then
  if [ "$(stat -c %s "$SESSION")" -lt 100 ]; then
    rm -f "$SESSION"
    log "chưa có session Zalo (bot chưa liên kết) — bỏ qua"
  else
    log "zalo session archived"
  fi
else
  rm -f "$SESSION"
  log "không đọc được session Zalo — bỏ qua"
fi

# ── Off-site copy ────────────────────────────────────────────────────────────
if [ -n "$REMOTE" ]; then
  log "uploading to $REMOTE"
  docker run --rm --env-file "$ENV_FILE" -v "$DEST_ABS":/data rclone/rclone \
    copy /data "$REMOTE" --include "*-$STAMP.*" --s3-no-check-bucket \
    || fail "không upload được lên $REMOTE"
  log "upload ok"
else
  log "BACKUP_REMOTE trống — chỉ giữ bản local"
fi

find "$DEST_ABS" -type f \( -name 'postgres-*' -o -name 'zalo-session-*' \) \
  -mtime "+$RETENTION_DAYS" -print -delete
log "backup complete, giữ $RETENTION_DAYS ngày trong $DEST_ABS"
