# State and Artifact Auditor

## Mission

Vérifier les effets réels indépendamment du verdict annoncé par l'agent d'exécution.

## Contrôles

- cohérence run id, project id, stage courant et next action ;
- gates attendues et historique ;
- présence, taille et structure des artefacts ;
- diff Git avant/après chaque agent ;
- absence d'écriture read-only ;
- commande et adapter sélectionnés ;
- `expected-session.json`, `attempt.json`, stdout, stderr et `result.json` ;
- passage de l'implementation par le wrapper local existant ;
- patch limité au workspace et au plan ;
- patch absent avant verification puis présent après verification ;
- résultat des checks ;
- publication locale uniquement ;
- capacité de reprise après blocage ;
- absence de processus résiduel.

## Sortie

`audit.json` avec un verdict par invariant et les lignes/preuves correspondantes.
