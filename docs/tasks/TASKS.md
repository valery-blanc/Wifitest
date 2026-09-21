# TASKS

## Architecture — décisions verrouillées (2026-09-21)
- [x] Transport ESP32 → téléphone : **USB-CDC (OTG)**
- [x] Plan de contrôle : **webservice sur Fez** (Traefik `wifitest.zitoon.com`, 24/7)
- [x] Plan de calcul : workers « pull » — **Anqa** (LAN, gratuit) + **RunPod pod multi-4090** (à la demande)
- [x] Usage distant 4G/5G confirmé → archi file-de-jobs publique
- [x] Capture : **PMKID d'abord**, repli handshake 4-way + deauth ; firmware éprouvé au départ
- [x] Cracking : `hashcat -m 22000`, attaque **en cascade** (candidats probables d'abord)
- [x] Hostinger écarté (VPS d'un ami)

## Jalons

### M0 — Pipeline de crack (prioritaire, test bout-en-bout sans RF)
- [x] `webservice/` : FastAPI (POST /jobs, GET /jobs/{id}, GET /jobs/next, POST result) + file (SQLite) + auth token
- [x] `worker/` (portable Anqa/RunPod/local) : poll + `hashcat -m 22000` + post résultat
- [x] Validé en local avec un **hash 22000 de test connu** → `found: hashcat!` (2026-09-21)
- [x] Bugs corrigés : BUG-001 (ordre routes), BUG-002 (cwd OpenCL hashcat)
- [x] DNS : wildcard `*.zitoon.com` déjà en place (rien à faire côté registrar)
- [x] Dockerfile webservice + compose isolé + route Traefik → **déployé sur Fez ET Avignon** (2026-09-21)
- [x] Validé bout-en-bout via `https://wifitest.zitoon.com` (submit → worker → found) (2026-09-21)
- [ ] Valider sur un vrai GPU (Anqa quand up, ou RunPod) — fait sur iGPU Tulear pour l'instant

**Prod déployée** : `https://wifitest.zitoon.com` (Fez actif + Avignon secours). Tokens dans
`~/Wifitest/deploy/.env` sur chaque nœud (générés, hors git). MÀJ : `cd deploy && git pull && docker compose up -d --build`.

### M1 — Capture RF  ⛔ BLOQUÉ (action matérielle requise)
- [!] **Brancher l'USB-C propre de la dev board ESP32-S2 sur Bruxelles** (elle peut rester
  montée sur le Flipper). Constaté 2026-09-21 : dev board seulement sur le GPIO du Flipper,
  Flipper en firmware officiel sans app WiFi/Marauder → ESP32 non joignable, rien ne capture.
- [ ] Après branchement : `esptool` détecte la puce → flasher firmware de capture (Marauder / WiFi Pen Tool)
- [ ] Capturer PMKID/handshake du réseau **"visitor"** (perso, mdp connu) → pcap → `22000`
- [ ] Repli handshake 4-way + deauth si pas de PMKID
- Réseau de test fourni : SSID **visitor** (mdp connu pour valider la crack via wordlist)

### M2 — App Android
- [ ] USB-CDC (OTG) : lire le hash depuis l'ESP32 (UsbManager)
- [ ] Client webservice : soumettre / poll / afficher (LAN + 4G/5G)
- [ ] Boucle complète capture → téléphone → Fez → Anqa → mot de passe

### M3 — Backend RunPod + cascade
- [ ] `worker-runpod/` : template pod multi-4090 + wordlists sur network volume + self-terminate
- [ ] Auto-spin sur Anqa down / tier lourd
- [ ] Plan d'attaque en tiers (candidats FAI → rockyou+règles → masques)

### M4 — Finitions
- [ ] UI progression, repli deauth robuste
- [ ] Durcissement sécurité webservice (rate limit, TTL, auto-suppression des hash)

## Done
- [x] Bootstrap `/vb-init` : CLAUDE.md, arborescence `docs/`, spec, `.gitignore`, git init + remote (2026-09-21)
