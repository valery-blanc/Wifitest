# FEAT-002 — Crack en cascade borné dans le temps

**Statut** : IN PROGRESS (2026-09-23)

## Contexte / besoin

Le worker ne faisait qu'**une seule passe** `hashcat -a 0` sur `visitor_wordlist.txt`
(quelques mots de passe connus). Résultat : tout crack qui n'est pas dans cette petite
liste renvoie `not_found` en quelques secondes, sans réellement chercher.

Besoin (demande Val, 2026-09-23) : une version **longue** (quelques minutes à ~1 h) qui
**teste beaucoup plus de possibilités**.

## Comportement

Le worker exécute une **cascade** d'attaques hashcat, du plus probable/rapide au plus large,
et **s'arrête au premier hit**. Un **budget temps global** borne l'ensemble ; chaque passe
reçoit `--runtime = temps restant` (elle s'auto-arrête sans dépasser le budget).

Ordre de la cascade :
1. **wordlist ciblée** (`WIFITEST_WORDLIST`, mots de passe connus) — instantané
2. **rockyou** (`WIFITEST_ROCKYOU`, ~14 M) — secondes
3. **rockyou + best64.rule** (livré avec hashcat, ×77 ≈ 1 Md) — minutes
4. **masque 8 chiffres** `?d?d?d?d?d?d?d?d` (dates, 10⁸) — ~min
5. **rockyou + suffixe 2 chiffres** `-a 6 rockyou ?d?d` (`motdepasse12`)
6. **rockyou + OneRuleToRuleThemAll.rule** (~52 k règles, si présent) — la passe la plus
   large, consomme l'essentiel du budget restant
7. **masque 10 chiffres** `?d?d?d?d?d?d?d?d?d?d` (numéros de tél, 10¹⁰) — balayage final

Chaque passe est interruptible (bouton **Stop** — sondage `GET /jobs/{id}/cancel` toutes les
3 s → kill hashcat → statut `stopped`). Progression postée régulièrement
(`POST /jobs/{id}/progress`, ~toutes les 30 s) pour éviter le requeue « stale » (15 min).

## Config (variables d'environnement du worker)

| Variable | Rôle | Défaut |
|---|---|---|
| `WIFITEST_WORDLIST` | wordlist ciblée (passe 1) | (aucune) |
| `WIFITEST_ROCKYOU` | rockyou (passes 2,3,5,6) | (aucune → passes rockyou sautées) |
| `WIFITEST_RULES` | règles custom (`;`-séparées) remplaçant best64/OneRule auto | (auto) |
| `WIFITEST_MASKS` | masques `-a 3` (`;`-séparés) remplaçant 8/10 chiffres | (auto) |
| `WIFITEST_MAX_RUNTIME` | budget total en secondes | `3600` (1 h) |

Ressources absentes → passe sautée proprement (dégradation gracieuse). best64 est cherché
dans `<dossier hashcat>/rules/best64.rule` ; OneRule dans le dossier de rockyou
(`OneRuleToRuleThemAll.rule`).

## Statut de résultat

Inchangé : `found | not_found | error | stopped`. `not_found` = budget épuisé (ou toutes les
passes terminées) sans hit. Une passe qui rate n'est pas une erreur (codes hashcat
0/1/2/3/4/5 = OK/épuisé/abort/runtime) ; `error` seulement si aucune passe n'a pu tourner.

## Impact

- `worker/worker.py` (+ copie `webservice/app/static/worker.py` pour le pod) : `crack()`
  réécrit en cascade.
- Anqa : `run_worker.bat` reçoit `WIFITEST_ROCKYOU` + `WIFITEST_MAX_RUNTIME` ;
  `OneRuleToRuleThemAll.rule` téléchargé dans `C:\Tools\wifitest\`.
- Pod RunPod : `bootstrap.sh` devra aussi fournir rockyou + rules + budget (à faire quand le
  pod sera validé).

## Cadre

⚖️ Usage : réseaux possédés / autorisés uniquement (audit de SES mots de passe WiFi).
