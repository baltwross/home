#!/bin/bash

# Test script for Roomba integration with Home Assistant

# Configuration
HOME_ASSISTANT_URL="http://localhost:8123"
AUTH_TOKEN="YOUR_LONG_LIVED_ACCESS_TOKEN"  # Replace with your token

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
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

# Test 1: Check Home Assistant is running
echo -e "\n${GREEN}=== Test 1: Checking Home Assistant Status ===${NC}"
ha_status=$(call_home_assistant "")
if [[ $? -eq 0 ]]; then
  echo -e "✅ Home Assistant is running"
  echo "Response: $ha_status"
else
  echo -e "❌ Could not connect to Home Assistant"
  exit 1
fi

# Test 2: Check if Roomba is available
echo -e "\n${GREEN}=== Test 2: Checking Roomba Integration ===${NC}"
roomba_state=$(call_home_assistant "states/vacuum.roomba" | jq -r '.state' 2>/dev/null)

if [[ "$roomba_state" == "null" || -z "$roomba_state" ]]; then
  echo -e "❌ Roomba entity not found. Checking available vacuum entities..."
  # List all available vacuum entities
  call_home_assistant "states" | jq -r '.[] | select(.entity_id | startswith("vacuum.")) | .entity_id'
  exit 1
else
  echo -e "✅ Roomba found with state: $roomba_state"
  
  # Get detailed status
  roomba_details=$(call_home_assistant "states/vacuum.roomba")
  echo -e "\nRoomba Details:"
  echo "Status: $(echo $roomba_details | jq -r '.state')"
  echo "Battery: $(echo $roomba_details | jq -r '.attributes.battery_level')"
  echo "Status: $(echo $roomba_details | jq -r '.attributes.status')"
fi

# Test 3: Test Roomba Controls
echo -e "\n${GREEN}=== Test 3: Testing Roomba Controls ===${NC}"
echo "This will test basic Roomba controls. Make sure the Roomba is on its dock."

# Function to test a Roomba command
test_roomba_command() {
  local command=$1
  local expected_state=$2
  
  echo -n "Testing '$command'... "
  call_home_assistant "services/vacuum/$command" POST '{"entity_id": "vacuum.roomba"}' > /dev/null
  sleep 5  # Give it time to execute
  
  current_state=$(call_home_assistant "states/vacuum.roomba" | jq -r '.state')
  
  if [[ "$current_state" == "$expected_state" ]]; then
    echo -e "✅ Success (State: $current_state)"
  else
    echo -e "❌ Failed (Expected: $expected_state, Got: $current_state)"
  fi
}

# Test start/stop
test_roomba_command "start" "cleaning"
sleep 10  # Let it run for a bit
test_roomba_command "return_to_base" "returning"

# Test 4: Test iPhone presence automation
echo -e "\n${GREEN}=== Test 4: Testing iPhone Presence Automation ===${NC}"

# Function to simulate iPhone presence change
simulate_iphone_presence() {
  local state=$1
  echo -n "Setting iPhone presence to '$state'... "
  
  call_home_assistant "states/input_boolean.iphone_home" POST "{\n    \"state\": \"$state\",
    \"attributes\": {\"friendly_name\": \"iPhone Home Status\"}
  }" > /dev/null
  
  # Verify the state was set
  current_state=$(call_home_assistant "states/input_boolean.iphone_home" | jq -r '.state')
  
  if [[ "$current_state" == "$state" ]]; then
    echo -e "✅ Success"
    echo "   Roomba should now be triggered by the automation..."
    echo "   Waiting 10 seconds to observe behavior..."
    sleep 10
    
    # Check Roomba state after the automation runs
    roomba_state=$(call_home_assistant "states/vacuum.roomba" | jq -r '.state')
    echo "   Roomba state after automation: $roomba_state"
  else
    echo -e "❌ Failed to set state"
  fi
}

# Simulate iPhone leaving
simulate_iphone_presence "off"

# Wait a bit then simulate iPhone returning
sleep 10
simulate_iphone_presence "on"

echo -e "\n${GREEN}=== Test Complete ===${NC}"
echo "Check the logs above to verify all tests passed successfully."

# Final status
echo -e "\n${GREEN}=== Final Status ===${NC}"
echo "iPhone Home Status: $(call_home_assistant "states/input_boolean.iphone_home" | jq -r '.state')"
echo "Roomba State: $(call_home_assistant "states/vacuum.roomba" | jq -r '.state')"
