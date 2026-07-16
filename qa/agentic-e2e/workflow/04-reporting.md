# Contrat de rapport

## Rapport par scénario

Chaque scénario doit fournir :

- identifiant, titre, environnement et durée ;
- préconditions exactes ;
- liste ordonnée des actions ;
- résultat attendu et résultat observé pour chaque checkpoint ;
- commandes, touches et valeurs saisies ;
- exit codes ;
- captures d'écran textuelles/DOM ;
- chemins des artefacts ;
- résumé du diff Git ;
- état des gates avant/après ;
- défauts trouvés ;
- statut final.

## Défaut

Un défaut doit contenir :

- titre précis ;
- gravité ;
- reproductibilité ;
- scénario et étape ;
- comportement attendu/observé ;
- étapes minimales de reproduction ;
- preuves ;
- impact utilisateur ;
- état préservé ou perdu ;
- action de récupération disponible ;
- zone de code probablement concernée, marquée comme hypothèse ;
- résultat du rejeu.

## Rapport final

Ordre obligatoire :

1. verdict global ;
2. workflow principal, étape par étape ;
3. couverture exécutée/non exécutée ;
4. défauts par gravité ;
5. bugs bloquant le premier vrai usage ;
6. défauts Textual ;
7. défauts CLI/adapters ;
8. invariants de sécurité ;
9. flakes ;
10. recommandations ordonnées ;
11. index des preuves.
