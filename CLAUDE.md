# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**WifiTest** — banc d'**audit de robustesse de mot de passe WiFi** (test de sécurité
autorisé, sur des réseaux dont Val possède/contrôle les identifiants). Le système est
composé de quatre briques qui se relaient :

1. **Dev board ESP32-S2** (sur le Flipper Zero, qui sert d'alim/écran — pas de logique) —
   capture le secret WPA : **PMKID d'abord**, repli **handshake 4-way + deauth**. Sortie hash `22000`.
2. **Téléphone Android** — lit le hash depuis l'ESP32 en **USB-CDC (OTG)**, puis le POST au
   **webservice** (HTTPS) et poll le résultat. Marche en LAN **et** en 4G/5G.
3. **Webservice / file de jobs sur Fez** (24/7, Traefik `wifitest.zitoon.com`) — plan de
   contrôle toujours joignable ; ne calcule PAS lui-même.
4. **Workers GPU « pull »** (sortie HTTPS, aucun port ouvert) — **Anqa** (LAN, gratuit, 9h-21h)
   en priorité, **RunPod pod multi-4090** (à la demande) pour les cas lourds ou si Anqa est down.
   `hashcat -m 22000`, attaque **en cascade** (candidats probables d'abord) → mot de passe renvoyé.

> ⚖️ **Cadre** : usage défensif / test de sécurité autorisé uniquement (auditer la
> solidité de SES propres mots de passe WiFi). Les fichiers de capture peuvent contenir
> des identifiants — ne jamais les committer dans le dépôt (voir `.gitignore` capture).

### Composants et commandes (RUN_CMD par brique)

Le projet n'a pas une seule commande de lancement : chaque brique se build/déploie
séparément. Le tableau ci-dessous est le référentiel `RUN_CMD` utilisé par le workflow.

| Composant | Dossier | Stack | Build / Déploiement (RUN_CMD) |
|---|---|---|---|
| Firmware capture ESP32-S2 | `firmware-esp32/` | firmware éprouvé (Marauder / WiFi Pen Tool), custom + tard | flash via `esptool`/Marauder |
| App Flipper (.fap) — **optionnelle** | `flipper-app/` | C, ufbt | `ufbt launch` *(hors chemin critique)* |
| App Android | `android/` | Kotlin + Gradle | `./gradlew installDebug` |
| Webservice / file de jobs | `webservice/` | Python (FastAPI) + Docker | déployé sur **Fez** via `/vb-deployFez` (Traefik `wifitest.zitoon.com`) |
| Worker Anqa | `worker-anqa/` | Python + hashcat (CUDA) | `python worker-anqa/worker.py` sur Anqa *(à confirmer)* |
| Worker RunPod | `worker-runpod/` | Python + hashcat + template pod | pod multi-4090 auto-spin *(cf. `/vb-gpu-loue`)* |

> **Détermination de la stack de chaque brique** : à figer dans `docs/specs/wifitest-spec.md`
> dès la première implémentation. Marquer `[TODO]` tant que non tranché.

## Chemins de fichiers

Toujours donner les chemins de fichiers au format Windows complet : `C:\dossier\sous-dossier\fichier.ext`

## Workflow Rules

### Task Tracking
For any task that involves more than 3 files or more than 3 steps:
1. BEFORE starting, create/update a checklist in `docs/tasks/TASKS.md`
2. Mark each sub-step with `[ ]` (todo), `[x]` (done), or `[!]` (blocked)
3. Update the checklist AFTER completing each sub-step
4. If the session is interrupted, the checklist is the source of truth for resuming work

### Resuming Work
When starting a new session or after /clear, ALWAYS:
1. Read `docs/tasks/TASKS.md` to check current progress
2. Identify the first unchecked item
3. Resume from there — do NOT restart completed work

### Documentation Synchronization (OBLIGATOIRE)

**À chaque demande de modification, bug fix ou nouvelle feature — quelle que soit
la façon dont elle est formulée (message direct, fichier temp_*.txt, description
orale) — TOUJOURS :**

1. **Créer ou mettre à jour le fichier de bug** (`docs/bugs/BUG-XXX-*.md`)
   ou de feature (`docs/specs/FEAT-XXX-*.md`) correspondant.

2. **Mettre à jour `docs/specs/wifitest-spec.md`** — OBLIGATOIRE, SANS EXCEPTION.
   Ce fichier est la source de vérité de l'application. Il doit refléter à tout
   moment le comportement réel du code. Mettre à jour :
   - La section concernée (capture Flipper/ESP32, protocole de transfert Android↔Anqa,
     pipeline hashcat, UI, persistance, architecture, algorithmes, etc.)
   - Le numéro de version en en-tête (FEAT-XXX / BUG-XXX)
   - La structure du projet si des fichiers sont ajoutés/supprimés
   - Les cas limites si un nouveau cas est géré
   Ne pas attendre qu'on le demande. Si la feature est trop petite pour un §
   dédié, intégrer l'info dans la section la plus proche.

3. **Mettre à jour `docs/tasks/TASKS.md`** — toujours, sans condition :
   ajouter l'entrée si elle n'existe pas, cocher `[x]` les étapes terminées.

Cette règle s'applique MÊME pour les petites modifications demandées directement
dans le chat. Si c'est trop petit pour un fichier BUG/FEAT dédié, au minimum
mettre à jour `docs/specs/wifitest-spec.md` si le comportement change.

### Règle de test et confirmation avant commit (OBLIGATOIRE)

**Aucun commit ne doit être créé avant que l'utilisateur ait testé et confirmé.**

Ordre impératif pour tout bug fix ou feature :

```
[code] → [docs] → [déployer/lancer le composant concerné] → [demander test] → [attendre OK] → [commit]
```

- Le composant à (re)lancer dépend de la brique touchée — voir le tableau
  **Composants et commandes** ci-dessus (ESP32, Flipper, Android, serveur Anqa).
- Le commit regroupe TOUJOURS : code source + fichiers de doc + TASKS.md
- Si l'utilisateur signale un problème après test → corriger, re-déployer / relancer,
  re-demander confirmation AVANT de committer
- **Si un crash ou une erreur est découvert lors du test** → créer `docs/bugs/BUG-XXX-*.md`
  (même si le problème a déjà été corrigé), mettre à jour `docs/specs/wifitest-spec.md`
  avec la règle à retenir, et référencer dans `docs/tasks/TASKS.md`
- Aucune exception : même pour une modification d'une seule ligne

### Bug Fix Workflow
1. Documenter le bug dans `docs/bugs/BUG-XXX-short-name.md` (symptôme,
   reproduction, logs/logcat/traceback/monitor série, section spec impactée)
2. Analyser la cause racine AVANT d'écrire le fix (Plan Mode)
3. Implémenter le fix
4. Mettre à jour toute la documentation :
   - `docs/bugs/BUG-XXX-*.md` → statut `FIXED`, fix appliqué décrit
   - **`docs/specs/wifitest-spec.md` → OBLIGATOIRE** : mettre à jour la section du comportement corrigé
   - `docs/tasks/TASKS.md` → cocher `[x]` toutes les étapes terminées
5. **Déployer / lancer le composant concerné** (voir tableau Composants)
6. **Demander à l'utilisateur de tester et attendre sa confirmation explicite**
   — NE PAS committer avant que l'utilisateur confirme que c'est OK
7. Une fois confirmé : committer TOUS les fichiers modifiés en un seul commit
   (code + docs + TASKS.md) : `"FIX BUG-XXX: description courte"`

### Feature Evolution Workflow
1. Écrire la spec dans `docs/specs/FEAT-XXX-short-name.md` (contexte,
   comportement, spec technique, impact sur l'existant)
2. Analyser l'impact sur le code existant (Plan Mode) : risques, conflits,
   lacunes de la spec
3. Décomposer en tâches dans `docs/tasks/TASKS.md`
4. Implémenter
5. Mettre à jour toute la documentation :
   - `docs/specs/FEAT-XXX-*.md` → statut `DONE`, implémentation décrite
   - **`docs/specs/wifitest-spec.md` → OBLIGATOIRE** : intégrer le nouveau comportement dans la/les
     section(s) concernée(s), incrémenter la version
   - `docs/tasks/TASKS.md` → cocher `[x]` toutes les étapes terminées
6. **Déployer / lancer le composant concerné** (voir tableau Composants)
7. **Demander à l'utilisateur de tester et attendre sa confirmation explicite**
   — NE PAS committer avant que l'utilisateur confirme que c'est OK
8. Une fois confirmé : committer TOUS les fichiers modifiés en un seul commit
   (code + docs + TASKS.md) : `"FEAT-XXX: description courte"`
9. Mettre à jour CLAUDE.md si des règles d'architecture ont changé

## Règles ADB (OBLIGATOIRE)

**Ne JAMAIS utiliser `adb shell pm clear <package>` sur un launcher.**
Cette commande efface toutes les données du launcher (raccourcis, fond d'écran, disposition), pas seulement le cache icônes. C'est irréversible.

Pour vider uniquement le cache icônes du launcher après un changement d'icône :
```bash
adb shell am force-stop <launcher_package>   # tuer le launcher
adb shell am start -n <launcher_package>/.MainActivity  # relancer
# ou simplement laisser l'utilisateur appuyer sur Home
```

## Règle de build release (OBLIGATOIRE)

**À chaque build release (`./gradlew bundleRelease`) :**

1. **Incrémenter `versionCode`** dans `app/build.gradle.kts` AVANT de builder.
   Le Play Store rejette tout AAB dont le `versionCode` a déjà été uploadé.
   Règle : `versionCode` = numéro séquentiel strictement croissant, sans exception.
   Mettre à jour `versionName` si la version utilisateur change (ex: "1.1", "2.0").

2. **Vérifier `proguard-rules.pro`** avant d'activer ou de modifier la minification.
   La minification R8 (`isMinifyEnabled = true`) casse silencieusement :
   - **Retrofit + Gson** : les DTOs doivent être dans les règles `-keep`
   - **Hilt** : les classes `@HiltViewModel` et `@Inject` doivent être conservées
   - **Room** : les entités `@Entity` et DAOs `@Dao` doivent être conservées
   - **Media3 / ExoPlayer** : les classes du player doivent être conservées
   Le fichier `app/proguard-rules.pro` contient toutes ces règles.
   Si un nouveau DTO, ViewModel ou entité Room est ajouté, vérifier qu'il est couvert.

## Infrastructure — accès serveurs

Pour les détails complets de connexion (clés SSH, API tierces, services), lancer le
skill `/vb-connectAll`. Pour l'infra transverse (placement GPU, réseau, data), lire
`~/.claude/skills/infra.md`. Résumé :

| Serveur | Rôle | Connexion |
|---|---|---|
| **ANQA** `192.168.0.133` (eth) / `.112` (wifi) | Windows — **GPU RTX 5070 Ti = cracking hashcat** | `ssh -i ~/.ssh/id_ed25519_claude Val@192.168.0.133` |
| **Avignon** `192.168.0.222` | Debian 24/7 — Docker, secours | `ssh avignon` |
| **Tulear** `192.168.0.200` | Windows — hub repos `C:\WORK`, Android Studio | `ssh -i ~/.ssh/id_ed25519 val@192.168.0.200` |

> ⚠️ **ANQA (nœud de cracking)** : ne répond PAS au `ping` (ICMP filtré) → tester la
> dispo **en SSH**. IP flottante `.133` (ethernet) ⇄ `.112` (wifi, dongle Ralink parfois
> absent) → essayer `.133` puis `.112`. Disponible ~9h-21h (Genève).

## Création de skills personnalisés

Les skills Claude Code de Val suivent ces conventions :

- **Nom** : toujours préfixé `vb-` (ex: `vb-init`, `vb-release`) pour éviter les conflits avec les skills officiels
- **Structure** : un dossier par skill dans `~/.claude/skills/`, contenant un fichier `SKILL.md`
  ```
  ~/.claude/skills/vb-monSkill/SKILL.md   ✅
  ~/.claude/skills/vb-monSkill.md         ❌ (fichier plat non détecté)
  ```
- **Invocation** : `/vb-monSkill`
