#!/bin/bash
# Install user-level systemd services (no sudo needed)
# These start on user login, not system boot

set -e

mkdir -p ~/.config/systemd/user/
cp brave-cdp.service ~/.config/systemd/user/
cp captcha-bridge.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable brave-cdp.service
systemctl --user enable captcha-bridge.service

echo "User services installed."
echo ""
echo "Start now:"
echo "  systemctl --user start brave-cdp.service"
echo "  systemctl --user start captcha-bridge.service"
echo ""
echo "Check status:"
echo "  systemctl --user status brave-cdp.service"
echo "  systemctl --user status captcha-bridge.service"
echo ""
echo "View logs:"
echo "  journalctl --user -u brave-cdp.service -f"
echo "  journalctl --user -u captcha-bridge.service -f"
