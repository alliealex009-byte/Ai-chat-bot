#!/usr/bin/env bash
# Backup RIA's MongoDB (ria_database) to backups/ as a compressed archive. Keeps the newest 14.
# Cron example (daily 03:30):  30 3 * * * /opt/ria/scripts/backup.sh >> /opt/ria/logs/backup.log 2>&1
# Restore:  docker exec -i ria-mongo sh -c 'mongorestore --uri="mongodb://$MONGO_INITDB_ROOT_USERNAME:$MONGO_INITDB_ROOT_PASSWORD@localhost:27017/?authSource=admin" --archive --gzip --drop' < backups/FILE.archive.gz
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
DB="$(grep -E '^MONGO_DB_NAME=' .env | cut -d= -f2- || true)"; DB="${DB:-ria_database}"
mkdir -p backups
umask 077
OUT="backups/ria-$(date +%Y%m%d-%H%M%S).archive.gz"
# Credentials are read from the container's own environment, so no password appears on the host command line.
docker exec ria-mongo sh -c "mongodump --uri=\"mongodb://\$MONGO_INITDB_ROOT_USERNAME:\$MONGO_INITDB_ROOT_PASSWORD@localhost:27017/?authSource=admin\" --db $DB --archive --gzip" > "$OUT"
[ -s "$OUT" ] || { rm -f "$OUT"; echo "Backup failed (empty file)" >&2; exit 1; }
echo "Backup written: $OUT ($(du -h "$OUT" | cut -f1))"
ls -1t backups/ria-*.archive.gz | tail -n +15 | xargs -r rm -f
