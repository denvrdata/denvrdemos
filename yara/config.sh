#!/bin/bash

set -e

ROOT=$(pwd)

n=0
ngc_api_key=""
prompt="Entry your NGC API Key (nvapi-****): "
while IFS= read -p "$prompt" -r -s -n 1 char
do
    # Exit immediately if they hit enter
    if [[ $char == $'\0' ]]
    then
        break
    fi

    # Print the prefix and suffix to help users confirm that they entered the key correctly
    if [[ $n -gt 8 ]] && [[ $n -lt 65 ]]
    then
        prompt="*"
    else

        prompt="$char"
    fi

    # Update the saved key and the count increment
    ngc_api_key+="$char"
    ((n=n+1))

    # NOTE: AFAICT all NVIDIA personal access tokens are 70 characters long
    # Exit if our input has exceeded the 70 character standard key length.
    # This help us avoid a double copy situation.
    if [[ $n == 70 ]]
    then
        break
    fi
done

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

# Just to make sure we don't hit any permissions issues
chmod -R a+w data

echo 'Starting docker services'
time sudo docker compose up -d

echo "Configuration complete. Open ${IP}.nip.io in your browser."

