# SmartHome Automation

A collection of scripts and configurations for home automation, including Roomba diagnostics and monitoring tools.

## Features

- Roomba diagnostics and monitoring
- iPhone monitoring scripts
- Home Assistant configurations

## Detailed Setup Instructions

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-name>
    ```

2.  **Configure Home Assistant Secrets:**
    *   Create a `secrets.yaml` file inside the `homeassistant` directory: `homeassistant/secrets.yaml`.
    *   Populate it with your iRobot Roomba credentials:
        ```yaml
        # iRobot Roomba Credentials
        # Replace these placeholders with your actual Roomba BLID and Password
        irobot_blid: "YOUR_IROBOT_BLID"
        irobot_password: "YOUR_IROBOT_PASSWORD"
        ```
    *   The main `homeassistant/configuration.yaml` relies on these secrets for Roomba integration.

3.  **Configure Environment Variables for Scripts:**
    *   Copy the example environment file `.env.example` to a new file named `.env`:
        ```bash
        cp .env.example .env
        ```
    *   Edit the `.env` file and provide your specific details:
        *   `IPHONE_IP`: The IP address of the iPhone you want to monitor.
        *   `HOME_ASSISTANT_URL`: The full URL of your Home Assistant instance (e.g., `http://localhost:8123` or `http://your-home-assistant-ip:8123`).
        *   `HA_ACCESS_TOKEN`: A Long-Lived Access Token for Home Assistant. You can generate this from your user profile page in Home Assistant (click on your user icon at the bottom of the sidebar, then go to 'Long-Lived Access Tokens' and click 'Create Token').

4.  **Start Home Assistant:**
    *   Ensure you have Docker and Docker Compose installed.
    *   Run the following command from the root directory of this project to start Home Assistant in detached mode:
        ```bash
        docker-compose up -d
        ```

## Scripts

- `diagnose_roomba.sh`: Run diagnostics on Roomba devices.
- `monitor_iphone.sh`: This script is designed to monitor an iPhone's presence on the local network by pinging its IP address. It then updates an `input_boolean.iphone_home` entity in Home Assistant via the REST API to reflect whether the iPhone is connected ("on") or disconnected ("off") from the network.
    *   **Requirements:**
        *   This script should ideally run on a machine that is always on and resides on the same network as the iPhone and your Home Assistant instance. This could be the Docker host machine itself, or another reliable machine (e.g., a Raspberry Pi) on the network.
        *   It requires the following environment variables to be set (as detailed in the `.env` file, sourced from `.env.example`):
            *   `IPHONE_IP`: The IP address of the iPhone to monitor.
            *   `HOME_ASSISTANT_URL`: The URL of your Home Assistant instance.
            *   `HA_ACCESS_TOKEN`: Your Home Assistant Long-Lived Access Token.
    *   **Usage:**
        *   Make the script executable: `chmod +x monitor_iphone.sh`
        *   Run the script: `./monitor_iphone.sh` (it's recommended to run it in a detachable session, e.g., using `screen` or `tmux`, or as a systemd service for continuous operation).
- `setup_roomba.sh`: Setup and configure Roomba devices.

## License

This project is private and confidential.
