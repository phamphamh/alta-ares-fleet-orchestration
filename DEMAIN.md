# Demain chez Alta Ares — mode d'emploi

## Ce qui est prêt

- **Le planificateur** : `fleet-kit/handin/planner.py` (+ le dossier `fleet-kit/handin/aaplan/`).
- **La politique sans liaison** : `fleet-kit/handin/policy.py`.
- **La doc technique** (pour le jury) : `fleet-kit/handin/README.md`.
- **La présentation** : https://claude.ai/artifact/RVfTzW71oWUjrWhPDjgtgK (privée : partage-la via le menu Share si quelqu'un d'autre doit l'ouvrir).
- **Les démos à ouvrir dans le navigateur** (double-clic) :
  - `demo/plan-L4-401.html` : notre plan sur 100 drones.
  - `demo/baseline-L4-401.html` : le plan de référence, pour comparer.
  - `demo/linkloss-L3.html` : la coupure de liaison rejouée (appuie sur Espace pour lancer).

## Les chiffres à retenir

- Planificateur : **1,88 fois** la référence sur 32 scénarios jamais vus, **3 fois** sur les gros (100 drones). **Zéro plan invalide.**
- Sans liaison : **97,8 %** de la mission gardée, **zéro échec** sur 3 840 vols simulés, ça marche même avec le pire réseau testé (250 m, 50 octets/s).
- La phrase : « Deux infos, 7 à 14 octets, environ 4 messages par drone et par minute. Avec moins, on perd des points, jamais la sécurité. »

## Envoyer nos plans sur le tableau des scores (sur le wifi de la Hackathon House)

1. Récupère le **token** de l'équipe auprès des organisateurs (contact : jules.giraud@altaares.com).
2. Dans le Terminal :
   ```sh
   cd ~/orca/projects/altares/fleet-kit
   python3 -m fleetkit board-login --server http://192.168.2.19:8080 --team "TON_EQUIPE"
   ```
   Il te demande le token : colle-le, Entrée.
3. Envoie les 8 plans :
   ```sh
   python3 -m fleetkit submit-all my-plans/
   ```
4. Résultat attendu : une ligne « accepted » par scénario. Ouvre http://192.168.2.19:8080 dans le navigateur pour voir le tableau.

## Rendre le projet (avant demain midi)

Le dossier à rendre est **`fleet-kit/handin/`** (il contient `planner.py`, `policy.py`, `aaplan/`, `README.md`).
Demande aux organisateurs comment ils veulent le recevoir (lien Git, zip…).
Pour faire un zip : `cd ~/orca/projects/altares/fleet-kit && zip -r handin.zip handin -x "*/__pycache__/*"`
