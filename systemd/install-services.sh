#!/bin/bash
# Install systemd services for Brave CDP + CAPTCHA bridge
# Run as root or with sudo

set -e

USER=${1:-$SUDO_USER}
if [ -z "$USER" ]; then
    echo "Usage: sudo ./install-services.sh <username>"
    echo "Example: sudo ./install-services.sh leonardomoya"
    exit 1
fi

echo "Installing services for user: $USER"

# Copy services to systemd
sudo cp brave-cdp.service /etc/systemd/system/brave-cdp@$USER.service
sudo cp captcha-bridge.service /etc/systemd/system/captcha-bridge@$USER.service

# Reload systemd
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable brave-cdp@$USER.service
sudo systemctl enable captcha-bridge@$USER.service

# Start Brave now
sudo systemctl start brave-cdp@$USER.service
sleep 3

# Test CDP
if curl -s http://localhost:9222/json/version > /dev/null; then
    echo "Brave CDP is running!"
    # Start bridge
    sudo systemctl start captcha-bridge@$USER.service
    echo "Bridge started!"
else
    echo "WARNING: Brave CDP not responding. Check: sudo systemctl status brave-cdp@$USER"
fi

echo ""
echo "Services installed. Commands:"
echo "  sudo systemctl status brave-cdp@$USER"
echo "  sudo systemctl status captcha-bridge@$USER"
echo "  sudo journalctl -u brave-cdp@$USER -f"
echo "  sudo journalctl -u captcha-bridge@$USER -f"
