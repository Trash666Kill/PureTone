#!/bin/bash

# - Description: Configures the MPD (Music Player Daemon) sound device and restarts the MPD service.
# - Defines a function to search for a sound card matching the pattern "[K11" in /proc/asound/cards.
# - Updates the MPD configuration file (/etc/mpd.conf) with the detected sound card number.
# - Defines a function to restart the MPD service, exiting on failure if the restart is unsuccessful.
# - The main function orchestrates the process by calling the card detection and service restart functions.
# - If the sound card is not found, an error message is displayed, but the script continues to attempt restarting MPD.

grep_card() {
    # Define the pattern to search for the device
    DEVICE_PATTERN="\[K11"

    # Extract the sound card number associated with the device from /proc/asound/cards
    CARD_NUMBER=$(cat /proc/asound/cards | grep "$DEVICE_PATTERN" | awk '{print $1}')

    # Check if CARD_NUMBER is not empty before editing the file
    if [ -n "$CARD_NUMBER" ]; then
        # Replace the line 'device "plughw:..."' in /etc/mpd.conf with 'device "plughw:$CARD_NUMBER,0"'
        sed -i 's/device\s*"plughw:[^"]*"/device "plughw:'"$CARD_NUMBER"',0"/g' /etc/mpd.conf
    else
        # Print error message if DEVICE_PATTERN is not found
        printf "\e[31m*\e[0m ERROR: FAILED TO FIND DEVICE MATCHING PATTERN %s\n" "$DEVICE_PATTERN"
    fi
}

restart_mpd() {
    # Restart mpd service
    local SERVICE=mpd
    systemctl restart "$SERVICE"
    if [[ $? -ne 0 ]]; then
        printf "\e[31m*\e[0m Error: Failed to restart $SERVICE.\n"
        exit 1
    fi
}

restart_mympd() {
    # Restart mympd service
    local SERVICE=mympd
    systemctl restart "$SERVICE"
    if [[ $? -ne 0 ]]; then
        printf "\e[31m*\e[0m Error: Failed to restart $SERVICE.\n"
        exit 1
    fi
}

# Main function to orchestrate the setup
main() {
    grep_card
    restart_mpd
    restart_mympd
}

# Execute main function
main