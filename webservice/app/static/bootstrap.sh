#!/usr/bin/env bash
# Bootstrap d'un worker de crack sur un pod RunPod. Aucun secret ici : le token, l'URL du
# serveur et la clé RunPod (pour l'auto-terminate) arrivent par l'environnement du pod.
# L'image est nvidia/cuda (pas d'entrypoint). hashcat officiel, pas le paquet Ubuntu :
# le paquet ne parle pas CUDA et ne voit pas les GPU du pod.
set -u
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip p7zip-full curl ca-certificates pciutils
python3 -m pip install -q requests || pip3 install -q requests || true

HC_VER=7.1.2
mkdir -p /opt
curl -fsSL -o /opt/hashcat.7z "https://hashcat.net/files/hashcat-${HC_VER}.7z"
7z x -y -o/opt /opt/hashcat.7z
HC_DIR=/opt/hashcat-${HC_VER}
chmod +x "$HC_DIR/hashcat.bin" "$HC_DIR/hashcat" || true

cd /root
curl -fsSL "$WIFITEST_SERVER/static/worker.py" -o worker.py
curl -fsSL "$WIFITEST_SERVER/static/wordlist.txt" -o wordlist.txt
# rockyou : best effort, plafonné pour ne pas manger tout le garde-fou du pod.
curl -fsSL --max-time 180 -o rockyou.txt \
  "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt" || true
if [ -s rockyou.txt ]; then
  curl -fsSL --max-time 60 -o OneRuleToRuleThemAll.rule \
    "https://raw.githubusercontent.com/NotSoSecure/password_cracking_rules/master/OneRuleToRuleThemAll.rule" || true
fi

export WIFITEST_HASHCAT="$HC_DIR/hashcat.bin"
export LD_LIBRARY_PATH="${HC_DIR}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export WIFITEST_WORDLIST=/root/wordlist.txt
if [ -s /root/rockyou.txt ]; then
  export WIFITEST_ROCKYOU=/root/rockyou.txt
fi
# Pas de -d : hashcat prend toutes les cartes du pod.
unset WIFITEST_HASHCAT_EXTRA || true
# Préfixe runpod obligatoire (le serveur ne donne une part qu'à ces workers).
# L'id du pod rend chaque machine distincte.
export WIFITEST_WORKER_ID="runpod-${RUNPOD_POD_ID:-$$}"
export WIFITEST_POLL_SECONDS=6
export WIFITEST_IDLE_EXIT="${WIFITEST_IDLE_EXIT:-180}"

python3 /root/worker.py || true

# Garde-fou : le pod se termine lui-même après la sortie du worker (inactivité).
if [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_API_KEY:-}" ]; then
  curl -s -A curl/8.0 -H "Content-Type: application/json" \
    -d "{\"query\":\"mutation{podTerminate(input:{podId:\\\"$RUNPOD_POD_ID\\\"})}\"}" \
    "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" >/dev/null 2>&1 || true
fi
