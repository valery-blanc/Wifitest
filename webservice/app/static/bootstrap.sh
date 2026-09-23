#!/usr/bin/env bash
# Bootstrap d'un worker de crack sur un pod RunPod. Aucun secret ici : le token, l'URL du
# serveur et la clé RunPod (pour l'auto-terminate) arrivent par l'environnement du pod.
set -e
export DEBIAN_FRONTEND=noninteractive
# Image de base CUDA (sans entrypoint) : on installe hashcat + python ici.
apt-get update -qq && apt-get install -y -qq hashcat python3 python3-pip curl ca-certificates || true
python3 -m pip install -q requests 2>/dev/null || pip3 install -q requests 2>/dev/null || true

cd /root 2>/dev/null || cd /tmp
curl -fsSL "$WIFITEST_SERVER/static/worker.py" -o worker.py
curl -fsSL "$WIFITEST_SERVER/static/wordlist.txt" -o wordlist.txt
# rockyou pour une vraie attaque dictionnaire (best effort ; le pod cracke surtout du connu sinon)
curl -fsSL "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt" -o rockyou.txt 2>/dev/null || true
cat wordlist.txt rockyou.txt > allwords.txt 2>/dev/null || cp wordlist.txt allwords.txt

export WIFITEST_HASHCAT=hashcat
export WIFITEST_WORDLIST="$PWD/allwords.txt"
export WIFITEST_HASHCAT_EXTRA="--force"
export WIFITEST_WORKER_ID="${WIFITEST_WORKER_ID:-runpod}"
export WIFITEST_POLL_SECONDS=6
export WIFITEST_IDLE_EXIT="${WIFITEST_IDLE_EXIT:-180}"

python3 worker.py || true

# Garde-fou : le pod se termine lui-même après la sortie du worker (inactivité).
if [ -n "$RUNPOD_POD_ID" ] && [ -n "$RUNPOD_API_KEY" ]; then
  curl -s -A curl/8.0 -H "Content-Type: application/json" \
    -d "{\"query\":\"mutation{podTerminate(input:{podId:\\\"$RUNPOD_POD_ID\\\"})}\"}" \
    "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" >/dev/null 2>&1 || true
fi
