#!/bin/bash

# --- Configuration ---
# WiFI Network: http://192.168.1.254/cgi-bin/ipalloc.ha
IPHONE_IP="192.168.1.170"  # Your iPhone's IP address
HOME_ASSISTANT_URL="http://localhost:8123"
AUTH_TOKEN="YOUR_LONG_LIVED_ACCESS_TOKEN"  # You'll need to create this in Home Assistant

# --- State Tracking ---
# 0 = Disconnected, 1 = Connected
LAST_STATUS=1

# Function to update Home Assistant
update_home_assistant() {
  local state=$1
  curl -X POST "$HOME_ASSISTANT_URL/api/states/input_boolean.iphone_home" \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"state\": \"$state\"}" \
    -s -o /dev/null
  
  # Also log the update
  echo "[$(date)] Updated Home Assistant: iPhone is $state"
}

echo "Monitoring iPhone at IP: $IPHONE_IP"
echo "Home Assistant URL: $HOME_ASSISTANT_URL"
echo "Press Ctrl+C to stop."

# Initial state update
update_home_assistant "on"

# --- Main Loop ---
while true
do
  if ping -c 1 -t 1 "$IPHONE_IP" > /dev/null 2>&1; then
    # --- iPhone is CONNECTED ---
    if [ "$LAST_STATUS" -eq 0 ]; then
      echo "$(date): iPhone connected."
      osascript -e 'display notification "Your iPhone has reconnected to the Wi-Fi." with title "Network Monitor" subtitle "Device is back online" sound name "Blow"'
      update_home_assistant "on"
      LAST_STATUS=1
    fi
  else
    # --- iPhone is DISCONNECTED ---
    if [ "$LAST_STATUS" -eq 1 ]; then
      echo "$(date): iPhone disconnected."
      osascript -e 'display notification "Your iPhone has left the Wi-Fi." with title "Network Monitor" subtitle "Device is offline" sound name "Submarine"'
      update_home_assistant "off"
      LAST_STATUS=0
    fi

  # Wait for 60 seconds before checking again
  sleep 60
done
