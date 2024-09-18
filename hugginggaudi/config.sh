#!/bin/bash

set -e

ROOT=$(pwd)

echo 'Pulling down docker images'
time sudo docker compose pull

plaintext=""
prompt="Enter an admin password: "
while IFS= read -p "$prompt" -r -s -n 1 char
do
    # Exit when they hit enter
    if [[ $char == $'\0' ]]
    then
        break
    fi

    # Print a '*' for each input character
    prompt="*"

    # Update the saved key and the count increment
    plaintext+="$char"
done
passwd_hash=$(sudo docker run -t caddy:latest caddy hash-password -p "$plaintext")

IP=$(curl ifconfig.me)
mkdir -p .config/caddy
echo "Writing .config/caddy/Caddyfile"
tee .config/caddy/Caddyfile <<EOF
$IP.nip.io {
    reverse_proxy chatui:3000
    basicauth {
        admin $passwd_hash
    }
}
EOF

mkdir -p data/mongo
mkdir -p data/tgi
mkdir -p data/chatui
mkdir -p data/caddy

# Just to make sure we don't hit any permissions issues
chmod -R a+w data

echo 'Starting docker services'
time sudo docker compose up -d

echo "Configuration complete. Open ${IP}.nip.io/chat in your browser."
