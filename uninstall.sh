#!/bin/bash
set -euo pipefail

# macOS Process Exporter - Uninstall Script

PLIST_NAME="com.local.macos-process-exporter"
PLIST_DEST="/Library/LaunchDaemons/${PLIST_NAME}.plist"

echo "==> Uninstalling macOS Process Exporter..."

# Stop and remove the LaunchDaemon
if [ -f "${PLIST_DEST}" ]; then
    sudo launchctl unload "${PLIST_DEST}" 2>/dev/null || true
    sudo rm -f "${PLIST_DEST}"
    echo "    Removed LaunchDaemon."
fi

# Stop brew services (but don't uninstall - user may want them for other things)
echo "==> Stopping Prometheus and Grafana..."
brew services stop prometheus 2>/dev/null || true
brew services stop grafana 2>/dev/null || true

echo ""
echo "==> Done. The exporter is stopped and the LaunchDaemon removed."
echo "    Prometheus and Grafana have been stopped but not uninstalled."
echo "    To fully remove: brew uninstall prometheus grafana"
echo "    To remove Prometheus data: rm -rf \$(brew --prefix)/var/prometheus"
