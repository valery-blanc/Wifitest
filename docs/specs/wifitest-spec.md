# WifiTest — Spécification (source de vérité)

> **Version** : v0.5 (M1 : Marauder flashé, contrainte matérielle USB/SD identifiée, 2026-09-22)
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
  soumet hash 22000              sur FEZ (Traefik,               ◄─pull─ [Worker RunPod] (à la demande, PAYANT, multi-4090)
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
- Process qui poll le webservice (LAN `192.168.0.221` ou public), exécute `hashcat -m 22000`
  selon le plan d'attaque, poste progression + résultat. Tourne quand Anqa est up (9h-21h).
- **Stack** : Python + hashcat (Windows, CUDA, RTX 5070 Ti). `[TODO]` service vs tâche planifiée.

### 4.6 Worker RunPod (`worker-runpod/`)
- **Pod** (pas serverless) multi-RTX 4090, démarré à la demande (Anqa down ou tier lourd).
- Template : image hashcat + **wordlists sur network volume** (persistant → pas de re-download).
  Boot → pull du job → crack → post résultat → **self-terminate** (pas d'idle payé).
- **Stack** : `[TODO]` API RunPod (cf. skills `/vb-gpu-loue`, `/vb-rebuild-serverless`).
  3e compte RunPod dédié à WifiTest = choix d'isolation de facturation (optionnel).

## 5. Protocole webservice (esquisse)
`[TODO]` finaliser :
- `POST /jobs` → `{hash_22000, ssid, bssid, attack_plan?}` → `{job_id}`
- `GET /jobs/{id}` → `{status: queued|running|found|not_found|error, progress, password?, tried}`
- `GET /jobs/next` (worker, auth worker) → un job à traiter
- `POST /jobs/{id}/progress` / `POST /jobs/{id}/result`
- Auth : bearer token distinct téléphone / worker. HTTPS obligatoire.

## 6. Stratégie de cracking en cascade (le vrai levier)
Le job manager lance **du plus probable au moins probable**, s'arrête au 1er hit :
1. **Tier rapide (Anqa, gratuit)** : candidats ciblés = mots de passe **par défaut FAI**
   déduits du SSID (Livebox/SFR/Orange, formats hex/majuscules, numéros, dates) → puis
   rockyou + `best64` / `OneRuleToRuleThemAll`. Couvre la majorité des cas en secondes-min.
2. **Tier lourd (RunPod pod multi-4090)** : gros dicos, règles étendues, masques ciblés —
   seulement si le tier rapide échoue **ou** si Anqa est indisponible.

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
