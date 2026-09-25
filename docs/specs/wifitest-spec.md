# WifiTest — Spécification (source de vérité)

> **Version** : v0.8 (FEAT-004 : pod RunPod 4× RTX 4090 sur le compte 2, crédit affiché
> par compte réel. 2026-09-23)
> v0.7 : FEAT-002 cascade bornée ; FEAT-003 suivi, Play, budget, worker Anqa sans fenêtre.
> v0.6 : FEAT-001 UI pcap.zitoon.com upload→crack, Stop/Poubelle, worker Anqa persistant.
> **Nature** : banc d'audit de robustesse de mot de passe WiFi (test de sécurité autorisé).
> Ce fichier reflète à tout moment le comportement RÉEL du code. À mettre à jour à chaque
> FEAT-XXX / BUG-XXX.

## 1. Objectif

Récupérer **le plus vite possible** le mot de passe WPA/WPA2-PSK d'un réseau cible (audit
de robustesse) : capturer un hash crackable, puis le récupérer par attaque GPU en essayant
**les candidats les plus probables d'abord**.

⚖️ **Usage** : uniquement sur des réseaux dont Val contrôle les identifiants (audit
défensif). Les artefacts de capture contiennent des données sensibles → jamais commités,
supprimés après usage.

## 2. Où se joue la vitesse

Le temps total est **dominé par le crack**, pas par la chaîne de transfert (qui ne bouge
que quelques Ko). Une RTX 5070 Ti fait ~1-2 MH/s sur `-m 22000` (PBKDF2-HMAC-SHA1, lent).
Donc :
- Un mot de passe dans un dico (rockyou + règles) → secondes-minutes ✅
- Un WPA2 aléatoire de 10+ caractères → hors de portée, quelle que soit l'archi ❌

**Levier principal = stratégie d'attaque en cascade** (§6), pas le matériel de capture.

## 3. Architecture

### 3.1 Séparation plan de contrôle / plan de calcul
Le webservice (qui répond au téléphone) doit être **toujours joignable** → il ne vit PAS
sur le GPU. Le calcul GPU est **interchangeable** (Anqa ou RunPod).

```
[Téléphone Android] ──HTTPS──► [Webservice / file de jobs]  ◄─pull─ [Worker Anqa]   (LAN, 9h-21h, GRATUIT)
  soumet hash 22000              sur FEZ (Traefik,               ◄─pull─ [Worker RunPod] (à la demande, PAYANT, 4 pods × 1 GPU, compte 2)
  poll job_id ◄──────────────   wifitest.zitoon.com, 24/7)
                                 ── résultat / progression ──►
```

**Principe « pull »** : les workers viennent chercher les jobs en **sortie HTTPS**. Aucun
port ouvert sur Anqa (marche derrière la box, aucune config réseau).

### 3.2 Chaîne complète
```
[AP cible] --RF--> [Dev board ESP32-S2] --USB-CDC (OTG)--> [Téléphone] --HTTPS--> [Webservice Fez]
                                                                                        │
                                                        [Worker Anqa / RunPod] --pull--/
                                                                    │ hashcat -m 22000
                                                        mot de passe --> téléphone
```

## 4. Composants

### 4.1 Capture — dev board ESP32-S2 (`firmware-esp32/`)
- **Puce** : ESP32-S2 (module WROVER) sur la « Developer Board for Flipper Zero (Wi-Fi) ».
  ⚠️ Pas de Bluetooth (WiFi seul). Le Flipper = alim + écran + montage (**pas de logique**).
- **Méthode** : **PMKID d'abord** (clientless, 1 trame, sans deauth), **repli handshake
  4-way + deauth ciblé** si l'AP ne donne pas de PMKID.
- **Firmware** : partir d'un **firmware éprouvé** (ESP32 Marauder, ou ESP32 WiFi Penetration
  Tool de Risinek) plutôt que réécrire le monitor mode. Custom plus tard si besoin.
- **Sortie** : hash au format **`22000`** (unifié PMKID + EAPOL), lisible en USB-CDC.
- **État matériel constaté (2026-09-21, sur Bruxelles)** : Flipper en **firmware officiel**
  (dev `c9ab2b68`), **aucune app WiFi/Marauder/ESP installée** ; dev board branchée sur le
  **GPIO du Flipper uniquement** (pas sur son propre USB → ESP32 non joignable, firmware
  inconnu). ⚠️ **Pré-requis M1** : brancher l'USB-C **propre de la dev board** sur un PC
  (Bruxelles) pour flasher le firmware de capture (esptool) et parler à l'ESP32 en USB-CDC.
  Le montage sur le Flipper ne suffit pas — l'archi n'utilise pas le Flipper dans le flux.
- **⚠️ Constat majeur (2026-09-22) — la devboard officielle résiste à l'USB-CDC headless.**
  ESP32-S2 rev v0.0, flash 4 Mo, MAC `68:67:25:c0:38:a2`. Flashé **ESP32 Marauder** (option
  S2 devboard) avec succès (Hash verified). **Mais** : (1) au boot, Marauder **n'expose
  AUCUN port USB** (`no ports found`) — le build « flipper » route la série sur l'**UART
  GPIO vers le Flipper**, pas sur l'USB natif ; (2) Marauder **et** GhostESP sauvent le pcap
  sur **carte SD** (`/mnt/.../pcaps/`) ou streament en **UART vers le Flipper** — or la
  devboard **n'a pas de SD**. → Cette carte est conçue pour être pilotée **AVEC le Flipper**
  (SD + UI), pas en USB-CDC autonome. **Décision d'archi à revoir** (voir §11).
- **⛔ Constat bloquant (2026-09-22) — l'ESP32-S2 est 2.4 GHz UNIQUEMENT.** Le réseau cible
  **« visitor » est en 5 GHz** → **impossible à capturer avec cette carte** (ni voir, ni
  handshake, ni PMKID en 5 GHz). Vérifié : Sniff EAPOL/Raw sur canaux 2.4 GHz → beacons
  captés mais **0 trame EAPOL** (le handshake se joue en 5 GHz, invisible). Toute la chaîne
  en aval (pull pcap via COM, conversion `hcxpcapngtool`→22000, crack Anqa) est **validée**.
  **Pour le 5 GHz → carte dual-band Realtek RTL8720DN (BW16) + firmware 5Ghost** (projet
  `pingequalab/5ghost-wifi-lab`, flash.pingequa.com). Le pipeline aval reste identique.

### 4.2 App Flipper (`flipper-app/`) — OPTIONNELLE, hors chemin critique
Le Flipper n'est pas requis dans le flux de données (USB-CDC va de l'ESP32 au téléphone).
Une `.fap` de confort (afficher l'état, déclencher une capture) pourra venir plus tard.

### 4.3 App Android (`android/`)
- **Stack** : Kotlin + Gradle.
- **USB-CDC (OTG)** : lit le hash `22000` depuis l'ESP32 via l'API USB Host (`UsbManager`).
- **Réseau** : POST du hash au webservice `https://wifitest.zitoon.com`, polling du `job_id`,
  affichage du résultat/progression. Fonctionne en LAN **et** en 4G/5G.

### 4.4 Webservice / file de jobs (`webservice/`) — sur FEZ
- **Rôle** : API publique (auth par token) : `POST /jobs` (hash + SSID/BSSID), `GET /jobs/{id}`
  (statut/progression/résultat) ; côté worker : `GET /jobs/next` (pull), `POST /jobs/{id}/result`.
- **Stack** : `[TODO]` Python (FastAPI) + file légère (SQLite ou Redis). Conteneur Docker.
- **Déploiement** : route Traefik `wifitest.zitoon.com` sur le nœud actif — via `/vb-deployFez`.
  ⚠️ Fez est le nœud GQQFM de PROD : conteneur **isolé**, compose dédié, ne pas toucher GQQFM.
- **DNS** : ajouter l'enregistrement `wifitest.zitoon.com` chez le registrar (ACME émettra le cert).

### 4.5 Worker Anqa (`worker-anqa/`)
- Process qui poll le webservice (public `https://wifitest.zitoon.com`), exécute `hashcat -m 22000`
  selon le plan d'attaque, poste progression + résultat. Tourne quand Anqa est up (9h-21h).
- **Stack** : Python + hashcat **6.2.6** (Windows, CUDA, RTX 5070 Ti). Mesure du 23/09,
  même carte, `-m 22000 -d 1` : 6.2.6 = **1489 kH/s**, 7.1.2 = **1491 kH/s**. Pas
  d'écart utile, le worker reste sur 6.2.6. Le binaire 7.1.2 est seulement dans
  `C:\Tools\wifitest\hashcat-7.1.2\` (le pod, lui, l'utilise déjà : le paquet Ubuntu
  ne parle pas CUDA). Le worker lance hashcat en
  sous-process **suivable** (`subprocess.Popen`) et sonde `GET /jobs/{id}/cancel` toutes les 3 s :
  si annulation demandée, il tue hashcat et poste le statut `stopped`.
- **Déploiement (résolu)** : **tâche planifiée `WifiTestWorker`** sur Anqa (`ONLOGON`, session
  interactive de Val → accès GPU OK), qui lance `C:\Tools\wifitest\run_worker.bat`
  (env : SERVER, WORKER_TOKEN, HASHCAT, WORDLIST, `-d 1`). Arrêt manuel :
  `C:\Tools\wifitest\stop_worker.ps1`. ⚠️ hashcat doit être lancé depuis son dossier
  (`cwd = dossier hashcat`) sinon `./OpenCL/: No such file` (BUG-002).

### 4.6 Worker RunPod (FEAT-004)
- **4 pods d'une carte**, pas un pod de 4×4090 (ce format n'a presque jamais de stock).
  `WIFITEST_POD_COUNT` (défaut 4) × `WIFITEST_POD_GPU_COUNT` (défaut 1). Facturé sur le
  **compte 2** (`RUNPOD_API_KEY_2`). Le compte 1 (serverless `gqqfm-serverless`) n'est
  pas débité.
- **Cartes acceptées**, dans l'ordre : `gpuTypeIdList` (RunPod prend la **première qui
  a du stock**) — 4090, 3090, 4080 SUPER, 4080, 3090 Ti, 4070 Ti SUPER, 4070 Ti, 5090.
  Pas de A100/H100.
- Chaque pod reçoit une **part** du même job (`--skip` / `--limit` sur chaque passe).
  Le premier mot de passe trouvé annule les autres. Une part `not_found` ne clôt le job
  que lorsque les quatre ont fini. Un pod mort libère sa part au bout du délai stale.
- Image `nvidia/cuda:12.4.1-runtime-ubuntu22.04`. Bootstrap : hashcat **7.1.2**, wordlist,
  rockyou en best effort, puis **self-terminate**. Garde-fou `WIFITEST_MAX_POD_LIFE`
  (90 min) et sortie 180 s sans job. Sans job actif, le dispatcher termine les pods.
- `GET /jobs/next` : mode `pod` → seuls les workers `runpod*` ; `anqa` → l'inverse ;
  `auto` → les deux, et les pods ne démarrent que si Anqa est injoignable.
- Crédit UI : `clientBalance` par compte, avec e-mail masqué et nom du endpoint serverless.
  Le bandeau indique aussi « paie les pods » sur le compte 2. `clientLifetimeSpend` n'est
  pas lu (la clé répond Unauthorized sur ce champ, sans rapport avec le solde).

## 5. Protocole webservice (implémenté)
**Statuts d'un job** : `queued → running → (found | not_found | error | stopped)`.

Endpoints **téléphone/worker** (bearer token, tokens distincts) :
- `POST /jobs` (token téléphone) → `{hash_22000 (WPA*…), ssid, bssid, attack_plan?}` → `{job_id}`
- `GET /jobs/{id}` (token téléphone) → `{status, progress, password?, error?, tried, ssid}`
- `GET /jobs/next` (token worker) → un job à traiter (claim atomique)
- `POST /jobs/{id}/progress` / `POST /jobs/{id}/result` (token worker ; `result.status`
  accepte aussi `stopped`)
- `GET /jobs/{id}/cancel` (token worker) → `{cancel: bool}` — sondé par le worker pour
  interrompre hashcat.

Endpoints **UI** `pcap.zitoon.com` (session par cookie, mot de passe `WIFITEST_UI_PASSWORD`,
anti-bruteforce par IP) :
- `POST /api/login` / `POST /api/logout`
- `POST /api/upload` : pcap → `hcxpcapngtool` → 1 job par handshake/PMKID ; le pcap source
  est conservé dans `/data/pcaps/<uuid>.pcap` (référencé par les jobs pour la suppression).
- `GET /api/jobs` : liste (tableau UI triable, cellules copiables : SSID, mot de passe,
  date/heure, worker, statut).
- `POST /api/jobs/{id}/stop` (**bouton Stop**) : `queued → stopped` direct ; `running →`
  flag `cancel=1` (le worker interrompt hashcat et poste `stopped`). Réponses :
  `action: stopped | canceling | noop`.
- `POST /api/jobs/{id}/rerun` (**bouton Play**, FEAT-003) : relance un job terminé
  (`stopped|not_found|error|found`) → `queued` (reset état d'exécution), `budget_min` optionnel.
- `DELETE /api/jobs/{id}` (**bouton Poubelle**) : supprime le job **et** le pcap associé
  si plus aucun job ne le référence (`count_pcap_refs == 0`).
- **Suivi (FEAT-003)** : `GET /api/jobs` renvoie `started_at`, `phase` (passe en cours),
  `max_runtime` (budget) et `now` (horloge serveur) → l'UI affiche barre + passe + durée
  écoulée. `POST /api/upload` accepte `budget_min` (input minutes). Le worker poste `phase`
  via `/jobs/{id}/progress` et lit le budget par job renvoyé par `/jobs/next`.
- `GET /api/status` (Anqa joignable + mode + crédit RunPod), `POST /api/anqa/wake` (WOL via
  gqqfm-power), `POST /api/mode` (pod seul / anqa seul / pod si anqa down).

## 6. Stratégie de cracking en cascade (le vrai levier)

> **Implémenté (FEAT-002, 2026-09-23)** dans `worker/worker.py` : le worker exécute une
> cascade d'attaques hashcat bornée par un budget temps (`WIFITEST_MAX_RUNTIME`, défaut 1 h),
> arrêt au 1er hit, chaque passe recevant `--runtime = temps restant`. Ordre par défaut :
> (1) wordlist ciblée → (2) rockyou → (3) rockyou+best64 → (4) masque 8 chiffres →
> (5) rockyou+suffixe 2 chiffres → (6) rockyou+OneRuleToRuleThemAll → (7) masque 10 chiffres.
> Ressource absente = passe sautée. Interruptible (Stop) + progression postée (~30 s).
> Détails : `docs/specs/FEAT-002-crack-cascade.md`.

Le job manager lance **du plus probable au moins probable**, s'arrête au 1er hit :
1. **Tier rapide (Anqa, gratuit)** : candidats ciblés = mots de passe **par défaut FAI**
   déduits du SSID (Livebox/SFR/Orange, formats hex/majuscules, numéros, dates) → puis
   rockyou + `best64` / `OneRuleToRuleThemAll`. Couvre la majorité des cas en secondes-min.
2. **Tier lourd (RunPod pod multi-4090)** : gros dicos, règles étendues, masques ciblés —
   seulement si le tier rapide échoue **ou** si Anqa est indisponible.

**Motifs « humains » à couvrir explicitement** (leçon du test radar, mdp `alexandrealexandre1`
= prénom **doublé** + chiffre, ~20 bits d'entropie réelle malgré 19 caractères) :
- **règles de duplication** : hashcat `d$1` sur `alexandre` → `alexandrealexandre1` ;
- **attaque combinateur** `-a 1` (prénoms × prénoms) avec `-k '$1'`, ou hybride `-a 6/7` + masque `?d` ;
- ⚠️ `rockyou × rockyou` complet = infaisable (2×10¹⁴) → **réduire** à une liste de prénoms.
Une campagne générique (dico + règles single-word) **rate** ce motif ; une campagne
consciente du motif le casse en heures sur un seul GPU. C'est le cœur du « levier stratégie ».

## 7. Sécurité du webservice public
- HTTPS + **bearer token** (téléphone et workers, tokens distincts), pas d'endpoint anonyme.
- Hash/résultats **supprimés après récupération** ou TTL court ; ne pas logger les secrets.
- Rate limiting. Le service est un outil perso défensif — surface minimale.

## 8. Cas limites
`[TODO]` — au fil de l'implémentation :
- Anqa injoignable (9h-21h, IP flottante `.133`/`.112`, pas de ping) → bascule RunPod.
- Handshake incomplet / PMKID absent → repli deauth ; capture corrompue → rejeter.
- Mot de passe hors dico/masque → `not_found` après épuisement du plan.
- Coupure USB-CDC en cours de transfert → retry.
- Téléphone en 4G vs LAN → même URL publique, doit marcher des deux.

## 9. Structure du projet
```
C:\WORK\WifiTest\
├─ CLAUDE.md
├─ docs\{specs,bugs,tasks}\
├─ firmware-esp32\   (config/notes ; firmware éprouvé au départ)
├─ flipper-app\      (optionnel, plus tard)
├─ android\          (Kotlin, USB-CDC + client webservice)
├─ webservice\       (FastAPI + file de jobs, déployé sur Fez/Traefik)
├─ worker-anqa\      (Python + hashcat, poll)
└─ worker-runpod\    (template pod + worker, poll)
```

## 10. Plan par jalons (ordonné pour un test bout-en-bout au plus tôt)
- **M0 — Pipeline de crack** : ✅ **code validé en local le 2026-09-21** — `webservice/`
  (FastAPI + SQLite + auth) + `worker/` (hashcat -m 22000) crackent bout-en-bout un hash
  22000 de test (`WPA*01*...`, mdp `hashcat!`) sur l'iGPU de Tulear. Bugs trouvés/corrigés :
  [[BUG-001]] (ordre des routes), [[BUG-002]] (cwd OpenCL de hashcat). **Reste** : déploiement
  Fez+Avignon (Docker + Traefik `wifitest.zitoon.com`) et un vrai GPU (Anqa/RunPod).
- **M1 — Capture** : flasher l'ESP32-S2, capturer PMKID/handshake d'un AP de test à soi → hash 22000.
- **M2 — App Android** : USB-CDC (lire le hash) + client webservice (soumettre/poll/afficher).
  → boucle complète capture → téléphone → Fez → Anqa → mot de passe.
- **M3 — Backend RunPod + cascade** : worker pod multi-4090 (auto-spin), plan d'attaque en tiers.
- **M4 — Finitions** : repli deauth, UI progression, durcissement sécurité, auto-suppression.

## 11. Décision d'archi capture (ouverte depuis le constat du 2026-09-22)
La devboard officielle ne convient pas à un pilotage USB-CDC headless (§4.1). Trois routes :

- **Route A — Flipper + app Marauder/GhostESP (capture via le Flipper).** Le Flipper fournit
  la SD (pcap) et l'UI. Installer la .fap, lancer une capture PMKID/handshake (boutons),
  récupérer le pcap depuis la SD du Flipper via CLI → convertir en 22000 → cracker.
  ✅ marche avec le matériel tel quel. ❌ étape de capture pilotée aux boutons (peu automatisable).
- **Route B — firmware ESP32-S2 custom USB-CDC (cible « produit »).** Firmware minimal qui
  sniffe PMKID/EAPOL et **imprime la ligne 22000 sur l'USB natif** → colle à l'archi
  téléphone↔USB-CDC. ❌ tâche de dev firmware (toolchain ESP-IDF/Arduino, compilation, itération).
- **Route C — GhostESP/WiFi-Pen-Tool en mode AP + WebUI.** L'ESP monte son propre AP ; on
  pilote la capture et on télécharge le pcap en HTTP (sans Flipper, sans SD selon le firmware).
  Le téléphone rejoint l'AP de l'ESP. Compromis ; à valider selon le firmware.

Recommandation : **Route A pour prouver la chaîne capture→crack tout de suite** (matériel en
l'état), **Route B pour la version produit** (pilotage téléphone/USB). État actuel : la
devboard a **Marauder** flashé.
