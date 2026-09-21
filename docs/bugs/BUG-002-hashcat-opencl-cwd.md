# BUG-002 — hashcat : `./OpenCL/: No such file or directory`

**Statut** : FIXED (2026-09-21, découvert au test M0)
**Composant** : `worker/worker.py`

## Symptôme
Le job finissait en `status: error`, message `./OpenCL/: No such file or directory`. Le
crack ne démarrait pas.

## Cause racine
hashcat cherche son dossier `OpenCL/` (kernels) **relativement au répertoire courant**. Le
worker lançait hashcat depuis `worker/`, où ce dossier n'existe pas. En ligne de commande
ça marchait car on s'était placé (`cd`) dans le dossier hashcat.

## Fix
Lancer hashcat avec `cwd = dossier de l'exécutable` (`os.path.dirname(HASHCAT)`).
Inoffensif pour un hashcat installé sur le PATH (dirname vide → `cwd=None`).

## Règle à retenir (→ spec §4.5)
Sur Anqa/RunPod, s'assurer que hashcat trouve ses kernels : soit un hashcat installé
proprement (kernels dans son share dir), soit lancer depuis son dossier. Le worker gère les
deux. Note : le **premier** run compile les kernels (lent, surtout iGPU) puis cache.
