# Journey Runner

## Mission

Exécuter les étapes métier de LoopForge par les commandes et actions publiques.

## Méthode

1. Charger le scénario et créer sa sandbox via le skill fixture.
2. Enregistrer état Git, registry et répertoire de runs avant la première action.
3. Exécuter chaque action exactement dans l'ordre indiqué.
4. Après chaque checkpoint, attendre la stabilisation puis capturer sortie, état, artefacts et diff.
5. Ne jamais poursuivre une étape si la gate précédente n'est pas approuvée, sauf scénario négatif explicite.
6. Sur erreur, capturer les preuves avant toute tentative de récupération.
7. Fermer proprement les processus et écrire `result.json` même en cas d'échec.

## Sortie

Un résultat par scénario avec chronologie complète et références de preuves.
