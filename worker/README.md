# worker — crack portable WifiTest

Tire les jobs du webservice (sortie HTTPS), lance `hashcat -m 22000`, poste le résultat.
Le hash `22000` étant portable, le **même** worker tourne sur **Anqa** ou dans un **pod
RunPod** (ou en local pour les tests). Aucun port entrant requis (modèle « pull »).

## Prérequis
- Python 3.11+, `pip install -r requirements.txt`
- `hashcat` accessible + un backend GPU (CUDA sur Anqa/RunPod ; OpenCL iGPU en test local)

## Variables d'environnement
- `WIFITEST_SERVER`        URL du webservice (ex: `https://wifitest.zitoon.com`)
- `WIFITEST_WORKER_TOKEN`  token worker (obligatoire)
- `WIFITEST_HASHCAT`       chemin de hashcat (défaut `hashcat`)
- `WIFITEST_WORDLIST`      wordlist pour l'attaque `-a 0` (M0)
- `WIFITEST_HASHCAT_EXTRA` args hashcat en plus (ex: `--force -O`)
- `WIFITEST_WORKER_ID`     id du worker (défaut : hostname)
- `WIFITEST_POLL_SECONDS`  intervalle de poll si file vide (défaut 10)

## Lancer
```bash
WIFITEST_SERVER=https://wifitest.zitoon.com WIFITEST_WORKER_TOKEN=yyy \
  WIFITEST_WORDLIST=/path/rockyou.txt python worker.py          # boucle
python worker.py --once                                          # un seul job (tests)
```

## Notes hashcat
- hashcat cherche son dossier `OpenCL/` de kernels **dans son CWD** → le worker lance
  hashcat avec `cwd = dossier de l'exécutable` (transparent pour un hashcat du PATH). Voir
  `docs/bugs/BUG-002`.
- Le **premier** run compile les kernels (long, surtout sur iGPU) puis les met en cache.
- Un `401/403` au claim = mauvais token → le worker **s'arrête** (pas de boucle zombie).
