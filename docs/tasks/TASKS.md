# TASKS

## ⏭️ REPRISE — état au 25/09
- **Dernier commit** : FEAT-004 (ce commit) — 4 pods × 1 GPU, `gpuTypeIdList`, crédit
  identifié par compte. Poussé sur `main`. Val : « je valide en l'état ».
- **Déploiement** : webservice **Fez** (actif) + **Avignon** (secours) à jour du code FEAT-004.
  **Worker Anqa** : le processus tourne encore l'ancien `worker.py` (pas recopié ; inutile
  tant que le mode est `pod`, Anqa ne reçoit pas de job). Le fichier du dépôt, lui, sait
  découper en parts. Hashcat Anqa reste **6.2.6** (7.1.2 mesurée identique, 1489 vs 1491 kH/s,
  binaire posé à côté dans `C:\Tools\wifitest\hashcat-7.1.2\`, non branché).
- **Tests** : pas de suite automatisée dans ce projet. Validations **manuelles en réel** sur
  GPU Anqa (réseau `radar`), mesurées au commit `9aeadce` : cascade (90 s), Stop en file/en
  cours, Poubelle+pcap, barre/passe/budget par job, Play.
- 🔴 **À FAIRE EN PREMIER** : rien de bloquant.
- 🧨 **HORS PÉRIMÈTRE / réfuté** : `Sunrise_1494918` n'est PAS un réseau de Val (« non/pas
  sûr », 23/09) → crack **arrêté**, jobs + pcap **purgés**. Ne pas re-cracker. Avant tout
  crack d'un SSID à nom de box FAI → **demander confirmation** (mémoire
  `wifitest-perimetre-autorisation`).
- ⏳ **Ouvert (avec motif)** : capture **5 GHz** bloquée matériel (carte BW16 à acquérir) ;
  app **Android** M2 non démarrée ; candidats **FAI déduits du SSID** (raffinement de la
  cascade FEAT-002) ; durcissement sécurité webservice (rate limit/TTL).
- **FEAT-004** : commité, déployé. **4 pods × 1 GPU** sur le compte 2, `gpuTypeIdList`
  (4090, 3090, 4080 SUPER, 4080, 3090 Ti, 4070 Ti SUPER, 4070 Ti, 5090 — la première en
  stock). Mode UI encore sur **`pod`** : le prochain pcap loue jusqu'à 4 cartes.
  🔴 **Pas rejoué en réel** : l'essai du 23/09 n'a trouvé aucun 4×4090, le job a été
  arrêté, rien facturé. Le découpage en parts n'a pas été vu sur un vrai pod.

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
- [x] Validé sur **vrai GPU Anqa (RTX 5070 Ti, CUDA 13.2)** via la prod → `found` (2026-09-22)

**Prod déployée** : `https://wifitest.zitoon.com` (Fez actif + Avignon secours). Tokens dans
`~/Wifitest/deploy/.env` sur chaque nœud (générés, hors git). MÀJ : `cd deploy && git pull && docker compose up -d --build`.

### M1 — Capture RF  ⛔ BLOQUÉ MATÉRIEL : cible 5 GHz, carte 2.4 GHz only
- [x] ESP32-S2 identifié, **GhostESP flashé** (build esp32s2-generic), app Flipper Ghost ESP OK.
- [x] Chaîne capture→crack **entièrement validée** côté outils : capture pcap sur SD Flipper,
  pull via COM (script `pull4.py` avec drain du bandeau), transfert Avignon, conversion
  `hcxpcapngtool`→22000, worker GPU Anqa prêt. (2026-09-22)
- [x] Route A retenue (via Flipper + app GhostESP + SD). Routes B/C écartées (spec §11).
- [!] **BLOCAGE** : « visitor » est en **5 GHz**, or ESP32-S2 = **2.4 GHz uniquement** →
  captures 2.4 GHz = beacons mais **0 EAPOL** (handshake 5 GHz invisible). Constat définitif.
- [ ] **Acquérir une carte dual-band RTL8720DN (BW16) + firmware 5Ghost** (pingequa) pour le 5 GHz.
- [ ] Une fois la BW16 en place : capturer handshake/PMKID « visitor » (5 GHz) → 22000 → Anqa.
- Astuce validation immédiate possible : capturer un handshake sur un SSID **2.4 GHz** perso.

### ✅ VALIDATION BOUT-EN-BOUT réussie (2026-09-22) — réseau 2.4 GHz « radar »
Handshake WPA2 de **radar** (2.4 GHz, canal 7) capté par le Flipper+GhostESP (Sniff Raw,
**AP sélectionné pour verrouiller le canal** + reconnexions d'un client 2.4 GHz → M1/M3 captés),
pull via COM (`pull4`/drain bandeau), conversion `hcxpcapngtool`→22000 sur Avignon, soumission
au webservice prod → **cracké** : `alexandrealexandre1`. Vérifié sur **iGPU Tulear** ET sur
**Anqa RTX 5070 Ti (CUDA)** via la prod. Toute l'archie (hors capture 5 GHz) est prouvée.
Leçon capture : verrouiller le canal (sélectionner l'AP) est indispensable, sinon le sniffer
hoppe et rate les trames de l'AP (M1/M3).
- [ ] Après branchement : `esptool` détecte la puce → flasher firmware de capture (Marauder / WiFi Pen Tool)
- [ ] Capturer PMKID/handshake du réseau **"visitor"** (perso, mdp connu) → pcap → `22000`
- [ ] Repli handshake 4-way + deauth si pas de PMKID
- Réseau de test fourni : SSID **visitor** (mdp connu pour valider la crack via wordlist)

### M2 — App Android
- [ ] USB-CDC (OTG) : lire le hash depuis l'ESP32 (UsbManager)
- [ ] Client webservice : soumettre / poll / afficher (LAN + 4G/5G)
- [ ] Boucle complète capture → téléphone → Fez → Anqa → mot de passe

### M3 — Backend GPU + cascade
- [x] **Worker Anqa armé** : hashcat 6.2.6 (CUDA) dans `C:\Tools\wifitest\`, `worker.py`,
  `visitor_wordlist.txt` (mdp connu), lanceur `run_worker.bat` (`-d 1` = RTX). Crack via
  `run_worker.bat --once` (ou boucle sans arg). Validé sur la prod (2026-09-22).
  Mesure 23/09 sur la 5070 Ti (`-m 22000 -d 1`) : 6.2.6 = 1489 kH/s, 7.1.2 = 1491 kH/s.
  Pas de bascule. 7.1.2 est installé à côté, non branché.
- [ ] `worker-runpod/` : template pod multi-4090 + wordlists sur network volume + self-terminate
- [ ] Auto-spin sur Anqa down / tier lourd
- [ ] Plan d'attaque en tiers (candidats FAI → rockyou+règles → masques) — ⚠️ tiers rockyou+règles(best64/OneRule)+masques **livrés par FEAT-002** (cascade bornée) ; reste les **candidats déduits du SSID** (défauts FAI).

### M4 — Finitions
- [ ] UI progression, repli deauth robuste — ⚠️ **UI progression livrée (FEAT-003)** : barre + passe + durée ; reste le repli deauth robuste (capture).
- [ ] Durcissement sécurité webservice (rate limit, TTL, auto-suppression des hash)

## Done
- [x] Bootstrap `/vb-init` : CLAUDE.md, arborescence `docs/`, spec, `.gitignore`, git init + remote (2026-09-21)

### FEAT-001 — Interface web pcap.zitoon.com
- [x] UI (design monitoring) : login mot de passe + anti-bruteforce, cookie session
- [x] Upload pcap → hcxpcapngtool (dans le conteneur) → hash 22000 + SSID → job(s)
- [x] Tableau des jobs (SSID, mot de passe, date/heure, worker, statut) : **triable par colonne**, cellules copiables (mdp clic-copie)
- [x] Bandeau : **statut Anqa + bouton WOL** (via gqqfm-power), **3 modes** (anqa/pod/auto), **crédit RunPod** (2 comptes, myself.clientBalance)
- [x] Déployé Fez + Avignon (Traefik pcap.zitoon.com), testé (login/upload/status/mode ; power joignable)
- [ ] **Phase 2** : dispatcher + pod RunPod (hashcat) auto-spin/stop selon le mode ; worker Anqa permanent — ⚠️ **worker Anqa permanent FAIT** (tâche `WifiTestWorker`, 23/09) + dispatcher validé ; **pod ne cracke pas encore**.
- [ ] Test utilisateur (demain) : UI complète + vrai crack via Anqa (WOL) et via pod RunPod — ⚠️ **Anqa : crack réel validé** (23/09) ; **pod RunPod reste à valider**.

#### FEAT-001 Phase 2 — dispatcher + pod RunPod (2026-09-23)
- [x] Fonctions pod : create (podFindAndDeployOnDemand) / terminate / list — **validé** (create→terminate→`pods:[]`).
- [x] Dispatcher (thread, nœud actif) : spin selon mode (anqa/pod/auto), arrêt sur inactivité, garde-fou durée max, nettoyage au démarrage. **Validé** : a bien spinné un pod pour un job en file (mode auto, Anqa down).
- [x] Watchdog détaché indépendant (arrêt forcé) — **validé** : a terminé le pod, `pods:[]`, aucune fuite de crédit. Coût des tests ~$0,25.
- [!] **Pod ne cracke pas encore** : au 1er test l'image `dizcza/docker-hashcat` avait un ENTRYPOINT (dockerArgs ignoré) ; passé à `nvidia/cuda:...` mais le worker n'a pas tourné (image de base **sans curl** → le fetch du bootstrap échouait). **Fix appliqué** (dockerArgs installe curl avant de fetch) — **à VALIDER demain** avec logs du pod en direct.
- [x] **Dispatcher DÉSACTIVÉ pour la nuit** (`WIFITEST_DISPATCHER=0` sur Fez, mode=anqa) → aucun pod ne spinnera. Réactiver : `WIFITEST_DISPATCHER=1` + restart.
- [ ] Demain : réactiver dispatcher, lancer 1 pod, tirer ses logs (RunPod), corriger le bootstrap si besoin → 1er crack via pod. ~~Worker Anqa permanent (tâche planifiée)~~ ✅ **FAIT (23/09)**.
- [x] **Divergence nœuds** : réglages pod (`DISPATCHER`, image, `POD_COUNT`, `POD_GPU_COUNT`, `POD_GPUS`, durée max) dans le **compose versionné** (25/09). Ils écrasent le `.env` local.

#### FEAT-001 — boutons Stop + Poubelle (2026-09-23)
- [x] DB : colonnes `cancel` + `pcap` (migration idempotente) ; request_cancel / is_canceled / delete_job / count_pcap_refs.
- [x] Upload : le pcap source est stocké dans `/data/pcaps/<id>.pcap` (référencé par les jobs).
- [x] Endpoints : `POST /api/jobs/{id}/stop` (queued→stopped, running→cancel), `DELETE /api/jobs/{id}` (job + pcap si plus référencé), `GET /jobs/{id}/cancel` (worker).
- [x] Worker : hashcat lancé en Popen + sondage annulation toutes les 3 s → kill → statut `stopped`.
- [x] UI : colonne Actions (■ Stop pour queued/running, 🗑 Poubelle avec confirmation) ; état « arrêté » ; tableau toujours triable/copiable.
- [x] Déployé Fez+Avignon, **testé** : stop (queued→stopped) + trash (job + pcap effacé) OK.
- [x] `worker.py` à jour recopié sur Anqa (`C:\Tools\wifitest\worker.py`) — Anqa réveillée 2026-09-23.
- [x] **Arrêt d'un crack en cours validé en réel** sur GPU Anqa (RTX 5070 Ti) : job long (rockyou×best64) `running` → `POST /api/jobs/{id}/stop` → `action:"canceling"` → worker tue hashcat → `stopped` en ~4 s.
- [x] Aussi validés en réel : stop en file (queued→stopped), poubelle (job + pcap effacé), crack normal (radar → `found`).
- [x] **Worker Anqa persistant** : tâche planifiée `WifiTestWorker` (ONLOGON, session interactive Val, run_worker.bat) créée + démarrée + validée (crack GPU OK). Helper `C:\Tools\wifitest\stop_worker.ps1` pour arrêter le worker.

#### FEAT-002 — crack en cascade borné (2026-09-23)
- [x] `worker/worker.py` : `crack()` réécrit en cascade (visitor → rockyou → +best64 → masque 8 → +2 chiffres → +OneRule → masque 10), budget `WIFITEST_MAX_RUNTIME` (défaut 1 h), `--runtime` par passe, progression postée (~30 s, anti-stale), interruptible (Stop).
- [x] Copie `webservice/app/static/worker.py` (pod).
- [x] Anqa : OneRuleToRuleThemAll.rule téléchargé (`C:\Tools\wifitest\`), best64 présent (livré hashcat), rockyou présent ; `run_worker.bat` = WORDLIST(visitor)+ROCKYOU+MAX_RUNTIME=3600 ; tâche `WifiTestWorker` relancée.
- [x] Testé (budget 90 s) : cascade enchaîne rockyou → rockyou+best64 → budget épuisé → not_found (budget respecté).
- [x] Cascade validée : test 90 s (rockyou → best64 → budget épuisé) + cascade active en réel. (Le fichier re-testé par Val était `Sunrise` = hors périmètre → arrêté, cf. REPRISE.)
- [ ] Pod RunPod : `bootstrap.sh` devra fournir rockyou + rules + budget (quand le pod sera validé).

#### FEAT-003 — suivi d'avancement + Play + budget + worker sans fenêtre (2026-09-23)
- [x] DB : colonnes `phase`, `max_runtime` (migrations idempotentes) ; `create_job(max_runtime)`, `update_progress(phase)`, `requeue_job()`.
- [x] main.py : `/api/jobs` renvoie `started_at`/`phase`/`max_runtime`/`now` ; `/jobs/next` renvoie `max_runtime` ; `/jobs/{id}/progress` accepte `phase` ; `/api/upload` accepte `budget_min` ; **`POST /api/jobs/{id}/rerun`** (Play).
- [x] worker.py : budget lu depuis le job (sinon env), passe (`phase`) postée à chaque étape.
- [x] UI : input **Budget (min)** ; **barre de progression** + passe en cours + durée écoulée (ticker 1 s, horloge serveur) ; bouton **▶ Play** (relance stopped/not_found/error).
- [x] Déployé Fez+Avignon **sans interrompre le scan en cours** (hashcat continue ; job Sunrise resté `running`). Endpoints validés (rerun→409 sur running, app.html sert les éléments).
- [x] Anqa : worker.py **stagé** (actif au prochain redémarrage du worker) ; `run_worker.bat` logue dans `worker.log` ; tâche `WifiTestWorker` relancée via **VBS caché** (`launch_hidden.vbs`) → plus de fenêtre au prochain lancement.
- [x] Worker Anqa relancé (23/09) après arrêt du scan → nouveau worker.py chargé : passe affichée + budget par job validés en réel sur `radar`.
- [x] Validation Val : « ok déploie les nouvelles features » (feu vert) ; validation réelle radar OK (budget 120 s pris en compte, passe `wordlist ciblée (1/7)`, found).

#### FEAT-004 — 4 pods × 1 GPU + crédit identifiable (2026-09-23, validé en l'état 25/09)
- [x] Compte du pod confirmé en prod : `RUNPOD_API_KEY_2` (pas le compte de serverless 1).
- [x] 4 pods × 1 GPU, `gpuTypeIdList` (première carte en stock). Parts `--skip`/`--limit`.
- [x] `gpuCount` configurable ; création en variables GraphQL ; erreur visible dans le bandeau.
- [x] Crédit : e-mail masqué + endpoint + marque « paie les pods ». Plus de lecture de `clientLifetimeSpend`.
- [x] Bootstrap : hashcat 7.1.2 officiel, pas de `-d` (toutes les cartes), self-terminate conservé.
- [x] Réglages pod dans le compose versionné (dispatcher, image, gpu, count, durée max).
- [x] Premier essai (23/09) : **aucun pod** — Anqa a claim le job en 20 s malgré le mode `pod`. Corrigé : `/jobs/next` respecte le mode.
- [!] Crack réel via pod **non fait**. Essai 23/09 : RunPod sans stock pour un 4×4090 ;
  Anqa avait d'abord volé le job (corrigé : le mode `pod` ne lui donne plus rien). Job
  arrêté, aucun pod facturé. Le schéma 4×1 GPU est déployé mais pas rejoué.
- [x] Confirmation Val (25/09) : « je valide en l'état » → commit + push.
