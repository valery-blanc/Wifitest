# FEAT-001 — Interface web pcap.zitoon.com (upload → hash → crack → affichage)

**Statut** : IN PROGRESS (2026-09-22)

## Contexte / besoin
Une page web publique **https://pcap.zitoon.com**, protégée par **mot de passe** (même
design que monitoring.zitoon.com), qui permet :
1. d'**uploader un fichier pcap** ;
2. un bouton qui **appelle Fez/Avignon** pour extraire le hash (`hcxpcapngtool` → `22000` + SSID) ;
3. puis **Anqa** (ou un pod RunPod si Anqa down) pour **cracker** ;
4. **affiche SSID + mot de passe** sur la même page, en asynchrone (même longtemps après).

## Architecture
Extension du **webservice** existant (FastAPI, file de jobs) :
- **Auth UI** : mot de passe (env `WIFITEST_UI_PASSWORD`) + cookie de session signé
  (itsdangerous), anti-bruteforce par IP (comme monitoring). Distinct des tokens worker/téléphone.
- **Upload** : `POST /api/upload` (multipart) → pcap temporaire → **hcxpcapngtool** (dans le
  conteneur, sur Fez/Avignon) → lignes `22000` + SSID → **crée un job par réseau** dans la file.
- **Crack** : les **workers** existants (Anqa, RunPod) tirent les jobs et postent le résultat.
- **Affichage** : `GET /api/jobs` (session) → la page **poll** et rend des cartes (SSID, statut,
  mot de passe). Résultats **persistants** (SQLite) → visibles même en revenant plus tard.
- **Route** : Traefik `pcap.zitoon.com` → conteneur webservice (réseau `web`), sur Fez+Avignon.

## Fallback GPU (décidé)
- Si Anqa indisponible → **pod RunPod** (pas serverless : job long/à état, multi-GPU).
- GPU cible : **RTX 4090 (ou 5090), multi-GPU** — meilleur rapport H/s/$ pour WPA (`-m 22000`,
  borné SHA1). Éviter A100/H100 (mauvais deal pour hashcat WPA).
- Dispatch : si aucun worker n'a pris le job après un délai ET Anqa down → spin d'un pod RunPod
  (API RunPod + template hashcat+wordlists ; nécessite clé API RunPod + template — à activer).

## Sécurité
- HTTPS (Traefik/ACME). Mot de passe + anti-bruteforce. Les pcap/hash contiennent des
  identifiants → stockage temporaire, ne pas exposer sans session. Uploads limités en taille.
- ⚖️ Usage : réseaux possédés / autorisés uniquement.
