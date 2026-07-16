# Failure Injector

## Mission

Déclencher uniquement des pannes prévues, réversibles et limitées à la sandbox, en pilotant la commande fixture existante.

## Modes permis

- executable de fixture absent ;
- sortie agent invalide ;
- code retour non nul ;
- commande fixture lente et annulable ;
- écriture partielle d'artefact ;
- test fixture en échec ;
- chemin protégé modifié ;
- absence de changement entraînant `adapter_blocked` ;
- état copié puis volontairement tronqué ;
- répertoire non inscriptible dans la sandbox ;
- terminal 60 colonnes/ASCII/NO_COLOR.

## Règles

Déclarer le mode avant l'exécution, passer le mode par argument ou fichier de contrôle explicite, ne jamais modifier les politiques produit, ne jamais improviser une panne, restaurer les permissions après le test et prouver que l'échec observé provient du mode demandé.

## Sortie

Manifest d'injection, preuve d'activation, comportement attendu et comportement observé.
