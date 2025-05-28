#!/bin/bash

card_number=$(cat /proc/asound/cards | grep '\[K11' | awk '{print $1}')

# Restart mpd service
restart_mpd() {
    local SERVICE=mpd
    systemctl restart "$SERVICE"
    if [[ $? -ne 0 ]]; then
        printf "\e[31m*\e[0m Error: Failed to restart $SERVICE.\n"
        exit 1
    fi
}