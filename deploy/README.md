# Déploiement WifiTest (Fez actif + Avignon secours)

Le webservice tourne en conteneur Docker isolé derrière le Traefik existant, exposé sur
`https://wifitest.zitoon.com`. **Ne touche pas à GQQFM.**

## Prérequis (une fois par nœud)
Le dépôt cloné sur le nœud (`~/Wifitest`), et un fichier `deploy/.env` (non commité) :
```
WIFITEST_PHONE_TOKEN=<token téléphone>
WIFITEST_WORKER_TOKEN=<token worker>
```

## Déployer / mettre à jour (sur Fez ET Avignon)
```bash
cd ~/Wifitest && git pull
cd deploy && docker compose up -d --build
# Route Traefik (file provider, rechargée à chaud) :
cp traefik/wifitest.zitoon.com.yml ~/docker/traefik/dynamic/
```

## Vérifier
```bash
curl -s https://wifitest.zitoon.com/health          # {"ok":true}
```

## Notes
- Le conteneur `wifitest` rejoint le réseau externe `web` ; Traefik le joint par son nom.
- Aucun port publié sur l'hôte : accès uniquement via Traefik (HTTPS).
- Sur Avignon (secours), Traefik est inerte tant qu'Avignon n'est pas actif — le conteneur
  tourne quand même, la route devient effective à la bascule.
- File de jobs SQLite **par nœud** (non répliquée) : un job en cours est perdu à une bascule
  (jobs courts et rejouables — acceptable). À revoir si besoin (M4).
