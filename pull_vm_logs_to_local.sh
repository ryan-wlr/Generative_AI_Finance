#!/usr/bin/env bash
set -euo pipefail

# Pull .log files from a GCE VM to your local machine.
# Usage:
#   bash pull_vm_logs_to_local.sh <zone> [instance] [vm_user] [remote_dir] [dest_dir]
# Example:
#   bash pull_vm_logs_to_local.sh us-central1-a instance-20260521-042726 weilerryan31 /home/weilerryan31/Generative_AI_Finance "$HOME/Downloads/finance-logs"
# Optional:
#   USE_IAP=1 bash pull_vm_logs_to_local.sh us-central1-a

ZONE="${1:-}"
INSTANCE="${2:-instance-20260521-042726}"
VM_USER="${3:-weilerryan31}"
REMOTE_DIR="${4:-/home/${VM_USER}/Generative_AI_Finance}"
DEST_DIR="${5:-$HOME/Downloads/finance-logs}"

if [[ -z "$ZONE" ]]; then
  echo "Error: zone is required."
  echo "Usage: bash pull_vm_logs_to_local.sh <zone> [instance] [vm_user] [remote_dir] [dest_dir]"
  exit 1
fi

mkdir -p "$DEST_DIR"

cmd=(gcloud compute scp --zone "$ZONE")
if [[ "${USE_IAP:-0}" == "1" ]]; then
  cmd+=(--tunnel-through-iap)
fi

cmd+=("${VM_USER}@${INSTANCE}:${REMOTE_DIR}/*.log" "$DEST_DIR/")

echo "Copying logs from ${VM_USER}@${INSTANCE}:${REMOTE_DIR} to ${DEST_DIR} ..."
"${cmd[@]}"

echo
echo "Done. Files in ${DEST_DIR}:"
ls -lh "$DEST_DIR"/*.log 2>/dev/null || echo "No .log files found in destination."
