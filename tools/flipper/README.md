# tools/flipper — récupérer les captures depuis la SD du Flipper (CLI série)

Utilitaires pour piloter le CLI du Flipper Zero par USB (COM) et récupérer les pcap
écrits par l'app GhostESP/Marauder sur la carte SD du Flipper.

- `flipper_cli.py COM3 "storage list /ext/apps_data/ghost_esp/pcaps"` : lance des commandes CLI.
- `flipper_pull.py COM3 <chemin_sur_SD> <sortie_locale> <taille_octets>` : télécharge un fichier binaire.

## Pièges (voir mémoire projet)
- **Quitter l'app GhostESP** sur le Flipper avant tout accès `storage` (l'app perturbe le CLI USB).
- Sur connexion fraîche, les scripts **drainent le bandeau d'accueil** avant d'envoyer la commande
  (sinon `storage read` ne renvoie que le prompt).
- Ne jamais tuer un process en pleine IO série (wedge le driver COM → débranch/rebranch requis).
