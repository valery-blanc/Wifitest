# FEAT-004 — Pod 4× RTX 4090 sur le compte 2, crédit identifiable

**Statut** : DONE en l'état (25/09) — Val valide, commité et poussé. Déployé Fez + Avignon.
Crack réel sur un pod **non rejoué** (pas de stock 4×4090 le 23/09 ; le schéma 4×1 GPU
n'a pas encore tourné).

## Contexte

Le dispatcher créait un pod **1× RTX 4090**. La spec parlait d'un « multi-4090 » qui
n'était pas dans le code. Le pod est facturé sur `RUNPOD_API_KEY_2` (compte 2,
`va***@gmail.com`), **pas** sur le compte 1 où vit serverless 1 (`gqqfm-serverless`,
`vb***@gmail.com`).

Le bandeau crédit affichait « Compte 1 » / « Compte 2 » et un montant, sans dire quel
e-mail ni quel endpoint. Le champ lu est le bon (`clientBalance`, le même que la console).
Ce qui était faux, c'est l'identité affichée : impossible de rapprocher le chiffre du
compte ouvert dans le navigateur. `clientLifetimeSpend` répond `Unauthorized` sur ces
clés ; il n'est pas le solde et n'est plus demandé.

## Comportement

- **4 pods × 1 GPU**, pas 1 pod × 4 GPU. `gpuTypeIdList` : RunPod choisit la première
  carte libre parmi 4090, 3090, 4080 SUPER, 4080, 3090 Ti, 4070 Ti SUPER, 4070 Ti, 5090.
- Un job est découpé en 4 parts (`job_slices`, `--skip`/`--limit`). Le premier hit annule
  les autres. Pas de 4 lignes dans l'UI.
- Image CUDA sans entrypoint. Bootstrap : hashcat 7.1.2 officiel + worker + wordlist.
- Le pod se termine tout seul (fin de worker, ou 180 s sans job). Garde-fou 90 min.
- Mode `pod` : Anqa ne peut plus claim un job (`GET /jobs/next` renvoie vide). Sans
  ça, Anqa prend le job en quelques secondes et le pod ne démarre jamais.
- Un pod orphelin (id perdu) est adopté, les doublons sont terminés.
- L'erreur de création RunPod est visible dans le bandeau (`pod_error`).
- Réglages pod dans `deploy/docker-compose.yml` (écrasent le `.env` local) pour que
  Fez et Avignon ne divergent plus.

## Coût

4× 4090 ≈ **1,36 $/h** (community) à **2,96 $/h** (secure), sur le compte 2.
Le solde lu le 23/09 était d'environ **5 $** sur ce compte. Une carte facture tant
que le pod existe.
