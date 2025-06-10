#!/bin/bash

# Configuration
HOME_ASSISTANT_URL="http://localhost:8123"
AUTH_TOKEN="YOUR_LONG_LIVED_ACCESS_TOKEN"  # Replace with your token

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

# Function to print warning message
print_warning() {
  echo -e "⚠️  ${YELLOW}$1${NC}"
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
  print_error "jq is not installed. Please install jq to run this script."
  exit 1
fi

# Test 1: Check Home Assistant connection
print_section "Testing Home Assistant Connection"
response=$(call_home_assistant "")
if [[ $? -eq 0 ]]; then
  print_success "Connected to Home Assistant"
  echo "Version: $(echo $response | jq -r '.version')"
else
  print_error "Failed to connect to Home Assistant"
  echo "Make sure Home Assistant is running and the URL is correct: $HOME_ASSISTANT_URL"
  exit 1
fi

# Test 2: Check if iRobot integration is installed
print_section "Checking iRobot Integration"
integrations=$(call_home_assistant "config/config_entries/flow/progress" | jq -r '.[] | select(.handler == "irobot_roomba") | .handler')

if [[ -n "$integrations" ]]; then
  print_success "iRobot integration is installed"
  echo "Configured instances: $integrations"
else
  print_warning "iRobot integration is not installed or configured"
  echo "You may need to set it up through the Home Assistant UI"
  echo "1. Go to Settings > Devices & Services"
  echo "2. Click '+ Add Integration'"
  echo "3. Search for 'iRobot'"
  echo "4. Follow the setup instructions"
fi

# Test 3: Check for vacuum entities
print_section "Checking for Vacuum Entities"
vacuum_entities=$(call_home_assistant "states" | jq -r '.[] | select(.entity_id | startswith("vacuum.")) | .entity_id')

if [[ -n "$vacuum_entities" ]]; then
  print_success "Found vacuum entities:"
  echo "$vacuum_entities"
  
  # Test each vacuum entity
  for entity in $vacuum_entities; do
    echo -e "\nTesting entity: $entity"
    entity_state=$(call_home_assistant "states/$entity")
    echo "State: $(echo $entity_state | jq -r '.state')"
    echo "Attributes: $(echo $entity_state | jq -c '.attributes | {battery_level: .battery_level, status: .status, friendly_name: .friendly_name}')"
  done
else
  print_error "No vacuum entities found"
  echo "This could be because:"
  echo "1. The iRobot integration is not properly set up"
  echo "2. The Roomba is not connected to your network"
  echo "3. The Roomba credentials are incorrect"
fi

# Test 4: Check logs for iRobot errors
print_section "Checking Home Assistant Logs for iRobot Errors"
log_entries=$(docker logs homeassistant 2>&1 | grep -i -E 'irobot|roomba|error|fail' | tail -n 20)

if [[ -n "$log_entries" ]]; then
  print_warning "Found relevant log entries:"
  echo "$log_entries"
else
  print_success "No relevant error logs found"
fi

# Test 5: Check network connectivity to Roomba
print_section "Testing Network Connectivity to Roomba"
roomba_ip=$(docker logs homeassistant 2>&1 | grep -i 'connecting to roomba' | tail -1 | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' || echo "")

if [[ -n "$roomba_ip" ]]; then
  echo "Found Roomba IP in logs: $roomba_ip"
  
  # Test ping to Roomba
  if ping -c 1 -t 1 "$roomba_ip" &> /dev/null; then
    print_success "Successfully pinged Roomba at $roomba_ip"
  else
    print_error "Could not ping Roomba at $roomba_ip"
    echo "Check if your Roomba is on the network and the IP is correct"
  fi
  
  # Test MQTT port (8883 for Roomba)
  if nc -z -w 1 "$roomba_ip" 8883 &> /dev/null; then
    print_success "Roomba MQTT port (8883) is open"
  else
    print_warning "Could not connect to Roomba MQTT port (8883)"
    echo "This might be normal if the Roomba is in sleep mode"
  fi
else
  print_warning "Could not determine Roomba IP from logs"
  echo "This might be because the Roomba hasn't connected yet"
fi

# Test 6: Check configuration.yaml
print_section "Checking Configuration"
if [[ -f "homeassistant/configuration.yaml" ]]; then
  echo "Current configuration.yaml contents:"
  cat homeassistant/configuration.yaml
else
  print_error "Could not find configuration.yaml"
  echo "Expected location: homeassistant/configuration.yaml"
fi

# Test 7: Check secrets.yaml
print_section "Checking Secrets"
if [[ -f "homeassistant/secrets.yaml" ]]; then
  echo "secrets.yaml exists"
  if grep -q "irobot" homeassistant/secrets.yaml; then
    print_success "Found iRobot credentials in secrets.yaml"
  else
    print_error "No iRobot credentials found in secrets.yaml"
    echo "Make sure you have the following in your secrets.yaml:"
    echo "irobot_blid: 'your_blid'"
    echo "irobot_password: 'your_password'"
  fi
else
  print_error "secrets.yaml not found"
  echo "Create a secrets.yaml file in the homeassistant directory"
fi

print_section "Diagnostics Complete"
echo -e "${GREEN}Review the output above for any issues.${NC}"
echo "If you're having trouble, check the following:"
echo "1. Is your Roomba connected to Wi-Fi?"
echo "2. Are the BLID and password correct in secrets.yaml?"
echo "3. Is the Roomba on the same network as Home Assistant?"
echo "4. Check the Home Assistant logs for more details"
