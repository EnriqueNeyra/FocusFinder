#!/bin/bash
set -e

echo "Starting setup..."

# Detect user and home directory
USER_HOME=$(eval echo ~${SUDO_USER:-$USER})
USERNAME=$(basename "$USER_HOME")
PROJECT_DIR="$USER_HOME/FocusFinder"
LOG_FILE="/var/log/focusfinder.log"

# 1. Install system packages
echo "Installing system packages..."
sudo apt update
sudo apt install -y \
  python3-pip \
  python3-opencv \
  python3-pil \
  python3-gpiozero \
  python3-spidev \
  python3-numpy \
  python3-smbus \
  python3-picamera2 \
  python3-libcamera \
  libcamera-apps \
  
# 2. Enable SPI
echo "Enabling SPI..."
sudo raspi-config nonint do_spi 0

# 3. Ensure IMX219 camera overlay in config.txt
CFG="/boot/firmware/config.txt"
if ! grep -q "^\[all\]" "$CFG"; then
  echo "Adding [all] section to $CFG..."
  echo "[all]" | sudo tee -a "$CFG" >/dev/null
fi
if ! grep -q "^dtoverlay=imx219" "$CFG"; then
  echo "Adding dtoverlay=imx219 to $CFG..."
  echo "dtoverlay=imx219" | sudo tee -a "$CFG" >/dev/null
fi

# 4. Create systemd service
SERVICE_PATH="/etc/systemd/system/focus-finder.service"

echo "Creating systemd service at $SERVICE_PATH..."

cat <<EOF | sudo tee $SERVICE_PATH > /dev/null
[Unit]
Description=FocusFinder python service
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 $PROJECT_DIR/main.py
WorkingDirectory=$PROJECT_DIR
StandardOutput=file:$LOG_FILE
StandardError=inherit
Restart=always
User=$USERNAME
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 5. Enable and start the service
echo "Enabling focus-finder service..."
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable focus-finder.service
sudo systemctl start focus-finder.service

echo "Setup complete!"
echo "Log output: sudo journalctl -u focus-finder.service -f"

# Prompt reboot
read -p "Do you want to reboot now? (y/n): " REBOOT
if [[ "$REBOOT" =~ ^[Yy]$ ]]; then
  echo "Rebooting..."
  sudo reboot
else
  echo "Reboot skipped. Please reboot manually for all changes to take effect."
fi