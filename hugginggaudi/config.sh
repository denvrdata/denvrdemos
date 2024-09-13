#!/bin/bash

set -e

ROOT=$(pwd)

IP=$(curl ifconfig.me)
mkdir -p .config/caddy
echo "Writing .config/caddy/Caddyfile"
tee .config/caddy/Caddyfile <<EOF
$IP.nip.io {
    reverse_proxy chatui:3000
}
EOF

echo 'Pulling down docker images'
time sudo docker compose pull

mkdir -p data/mongo
mkdir -p data/tgi
mkdir -p data/chatui
mkdir -p data/caddy

# Just to make sure we don't hit any permissions issues
chmod -R a+w data

echo 'Starting docker services'
time sudo docker compose up -d

echo "Configuration complete. Open ${IP}.nip.io in your browser."

