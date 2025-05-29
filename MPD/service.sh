#!/bin/bash

grep_card() {
    #Extract the sound card number associated with the FiiO K11 device from the file /proc/asound/cards
    CARD_NUMBER=$(cat /proc/asound/cards | grep '\[K11' | awk '{print $1}')

    #Replace the line 'device "plughw:..."' in the /etc/mpd.conf file with 'device "plughw:$CARD_NUMBER,0"'
    sed -i 's/device\s*"plughw:[^"]*"/device "plughw:'"$CARD_NUMBER"',0"/g' /etc/mpd.conf
}

# Restart mpd service
restart_mpd() {
    local SERVICE=mpd
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
}

# Execute main function
main