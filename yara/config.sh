#!/bin/bash

set -e

ROOT=$(pwd)

# NOTE: AFAICT all NVIDIA personal access tokens are 70 characters long
# This help us avoid a double copy situation.
read -r -n 71 -s -p 'Enter your NGC API Key: ' ngc_api_key

echo 'Writing key to .config/ngc-api-key'
echo "$ngc_api_key" > .config/ngc-api-key
chmod 600 .config/ngc-api-key

echo 'Writing key to docker environment variable in .config/nim.env'
echo "NGC_API_KEY=$ngc_api_key" > .config/nim.env

IP=$(curl ifconfig.me)
mkdir -p .config/caddy
echo "Writing .config/caddy/Caddyfile"
tee .config/caddy/Caddyfile <<EOF
$IP.nip.io {
    reverse_proxy webui:8080
}
EOF

if [[ -f "data/webui/docs/index.html" ]]
then
    echo "HTML docs already found. Skipping download."
else
    echo 'Downloading Denvr docs to data/webui/docs'
    mkdir -p data/webui/docs
    cd data/webui/docs
    wget -q https://docs.denvrdata.com/docs/sitemap.xml --output-document - | grep -E -o "https://docs\.denvrdata\.com[^<]+" | wget -q -E -i - --wait 0
    cd "$ROOT"
fi

echo 'Logging into nvcr.io'
cat .config/ngc-api-key | sudo docker login nvcr.io --username '$oauthtoken' --password-stdin

echo 'Pulling down docker images'
time sudo docker compose pull

mkdir -p data/nim
mkdir -p data/webui
mkdir -p data/caddy

echo 'Starting docker services'
time sudo docker compose up -d

echo "Configuration complete. Open ${IP}.nip.io in your browser."

