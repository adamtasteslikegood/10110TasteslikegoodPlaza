#!/usr/bin/env bash

# Configure logging flags, enforce SSL, and set automated backup time
# for the PostgreSQL Cloud SQL instance used by Vegangenius Chef.
#
# Usage:
#   ./gcloud_sql_instance_patch_backup_time.sh [BACKUP_START_TIME]
#
# BACKUP_START_TIME (optional) is in HH:MM (24-hour) format and defaults to 02:00.
#
# NOTE: These operations may restart the Cloud SQL instance.

set -euo pipefail

PROJECT_ID="comdottasteslikegood"
INSTANCE_ID="vegangenius-db"
BACKUP_START_TIME="${1:-02:00}"

echo "Patching Cloud SQL instance '${INSTANCE_ID}' in project '${PROJECT_ID}'..."
echo "Configuring logging flags..."
gcloud sql instances patch "${INSTANCE_ID}" \
  --database-flags=log_connections=on,log_disconnections=on,log_duration=on,log_checkpoints=on,log_lock_waits=on,log_temp_files=0,log_statement=ddl \
  --project="${PROJECT_ID}"

echo "Enforcing SSL for all connections..."
gcloud sql instances patch "${INSTANCE_ID}" \
  --require-ssl \
  --project="${PROJECT_ID}"

echo "Setting automated backup start time to ${BACKUP_START_TIME}..."
gcloud sql instances patch "${INSTANCE_ID}" \
  --backup-start-time="${BACKUP_START_TIME}" \
  --project="${PROJECT_ID}"

echo "Cloud SQL instance '${INSTANCE_ID}' has been patched successfully."