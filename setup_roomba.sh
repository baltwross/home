#!/bin/bash

# Configuration
HOME_ASSISTANT_URL="http://localhost:8123"
CONFIG_FILE="roomba_config.env"

# Function to load saved configuration
load_config() {
  if [[ -f "$CONFIG_FILE" ]]; then
    source "$CONFIG_FILE"
    if [[ -n "$HA_URL" && -n "$HA_TOKEN" ]]; then
      HOME_ASSISTANT_URL="$HA_URL"
      AUTH_TOKEN="$HA_TOKEN"
      return 0
    fi
  fi
  return 1
}

# Function to save configuration
save_config() {
  echo "HA_URL='$HOME_ASSISTANT_URL'" > "$CONFIG_FILE"
  echo "HA_TOKEN='$AUTH_TOKEN'" >> "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"
}

# Function to prompt for credentials
prompt_credentials() {
  read -p "Enter your Home Assistant URL [http://localhost:8123]: " url
  HOME_ASSISTANT_URL=${url:-http://localhost:8123}
  
  read -p "Enter your Home Assistant Long-Lived Access Token: " token
  while [[ -z "$token" ]]; do
    echo "Token cannot be empty!"
    read -p "Enter your Home Assistant Long-Lived Access Token: " token
  done
  AUTH_TOKEN="$token"
  
  # Verify the token works
  if verify_token; then
    save_config
    return 0
  fi
  return 1
}

# Function to verify the token works
verify_token() {
  echo -n "Verifying token... "
  response=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $AUTH_TOKEN" "$HOME_ASSISTANT_URL/api/")
  
  if [[ "$response" == "401" ]]; then
    echo "❌ Invalid token. Please check your token and try again."
    return 1
  elif [[ "$response" != "200" ]]; then
    echo "❌ Failed to connect to Home Assistant. Status code: $response"
    return 1
  else
    echo "✅ Token verified successfully"
    return 0
  fi
}

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to make API calls to Home Assistant
call_home_assistant() {
  local endpoint=$1
  local method=${2:-GET}
  local data=${3:-}
  
  curl -s -X $method \
    -H "Authorization: Bearer $AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    ${data:+-d "$data"} \
    "$HOME_ASSISTANT_URL/api/$endpoint"
}

# Function to print section header
print_section() {
  echo -e "\n${YELLOW}=== $1 ===${NC}"
}

# Function to print success message
print_success() {
  echo -e "✅ ${GREEN}$1${NC}"
}

# Function to print error message
print_error() {
  echo -e "❌ ${RED}$1${NC}"
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
  print_error "jq is not installed. Please install jq to run this script."
  exit 1
fi

# Get Home Assistant credentials
print_section "Home Assistant Setup"

# Try to load saved config first
if load_config; then
  echo -n "Found saved configuration. Use it? [Y/n] "
  read -r
  if [[ $REPLY =~ ^[Yy]$ || -z "$REPLY" ]]; then
    echo "Using saved configuration for $HOME_ASSISTANT_URL"
    if ! verify_token; then
      echo "Saved token is invalid. Please enter new credentials."
      prompt_credentials
    fi
  else
    prompt_credentials
  fi
else
  echo "No saved configuration found. Please enter your Home Assistant details."
  prompt_credentials
fi

# Main credentials loop
while ! verify_token; do
  read -p "Would you like to try again? (y/n) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Exiting..."
    exit 1
  fi
  prompt_credentials
done

# Get iRobot credentials
print_section "iRobot Account"
echo -e "\n${YELLOW}Note: This is your iRobot account email and password, not your Home Assistant credentials.${NC}"
echo -e "If you're not sure about your iRobot password, you can reset it at https://homesupport.irobot.com/"
echo

# Try to get saved email first
if [[ -n "$IROBOT_EMAIL" ]]; then
  read -p "iRobot Email [$IROBOT_EMAIL]: " email_input
  IROBOT_EMAIL="${email_input:-$IROBOT_EMAIL}"
else
  read -p "iRobot Email: " IROBOT_EMAIL
  while [[ -z "$IROBOT_EMAIL" ]]; do
    echo "Email cannot be empty!"
    read -p "iRobot Email: " IROBOT_EMAIL
  done
fi

# Don't show saved password for security
read -s -p "iRobot Password: " IROBOT_PASSWORD
while [[ -z "$IROBOT_PASSWORD" ]]; do
  echo -e "\nPassword cannot be empty!"
  read -s -p "iRobot Password: " IROBOT_PASSWORD
done
echo -e "\n✅ Got iRobot credentials"

# Check if iRobot integration is already configured
print_section "Checking for Existing iRobot Integration"
config_entries=$(call_home_assistant "config/config_entries/entry" | jq -r '.[] | select(.domain == "irobot_roomba") | .entry_id')

if [[ -n "$config_entries" ]]; then
  print_success "iRobot integration is already configured"
  echo "Entry ID: $config_entries"
  exit 0
fi

# Start the iRobot configuration flow
print_section "Starting iRobot Configuration"
flow_response=$(call_home_assistant "config/config_entries/flow" POST "{\"handler\":\"irobot_roomba\"}")
flow_id=$(echo "$flow_response" | jq -r '.flow_id')

if [[ -z "$flow_id" ]]; then
  print_error "Failed to start iRobot configuration flow"
  echo "Response: $flow_response"
  exit 1
fi

print_success "Started iRobot configuration flow"
echo "Flow ID: $flow_id"

# Submit the iRobot credentials
print_section "Submitting iRobot Credentials"
credentials_response=$(call_home_assistant "config/config_entries/flow/$flow_id" POST "{\"username\":\"$IROBOT_EMAIL\",\"password\":\"$IROBOT_PASSWORD\"}")

if [[ $? -ne 0 ]]; then
  print_error "Failed to submit iRobot credentials"
  echo "Response: $credentials_response"
  exit 1
fi

print_success "Successfully submitted iRobot credentials"
echo "Response: $credentials_response"

# Verify the integration was created
print_section "Verifying Integration"
sleep 5  # Give it a moment to create the integration

config_entries=$(call_home_assistant "config/config_entries/entry" | jq -r '.[] | select(.domain == "irobot_roomba") | .entry_id')

if [[ -n "$config_entries" ]]; then
  print_success "✅ iRobot integration successfully configured!"
  echo "Entry ID: $config_entries"
  echo "You can now use the Roomba in your automations"
else
  print_warning "⚠️  iRobot integration might not have been created successfully"
  echo "Please check the Home Assistant UI to verify the integration"
  echo "You may need to complete the setup manually"
fi

print_section "Next Steps"
echo "1. Check the Home Assistant UI for any additional setup steps"
echo "2. Restart Home Assistant if the Roomba doesn't appear"
echo "3. Check the logs for any errors: docker logs homeassistant"
