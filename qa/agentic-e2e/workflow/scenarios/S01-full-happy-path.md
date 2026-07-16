# S01 — Workflow complet nominal

## But

Valider qu'un utilisateur neuf peut terminer un run de A à Z avec les chemins produit réels.

## Préparation

1. Créer la fixture Python et son dépôt Git.
2. Configurer via la surface publique :

```text
/adapter local-adapter-fixture -- <python-absolu> <fixture.py> --scenario S01 --mode nominal
```

3. Vérifier que les politiques produit n'ont pas été modifiées.

## Parcours

1. `loopforge init`.
2. Ouvrir `loopforge` dans le TUI.
3. Home → projet → `n` → saisir la tâche.
4. Examiner puis approuver la tâche.
5. Lancer research et ouvrir `research.md` dans Evidence.
6. Lancer plan, ouvrir `plan.md`, approuver le plan.
7. Lancer implementation avec `local-adapter-fixture`.
8. Vérifier que l'attempt a été exécuté par `local_implementation_adapter.py` et que seul `src/calculator.py` est modifié.
9. Vérifier que l'adapter n'a ni généré le patch, ni exécuté les checks, ni demandé de publication.
10. Lancer verification et vérifier le passage des tests.
11. Lancer reviewer ; vérifier qu'il reste read-only.
12. Approuver la review.
13. Déclencher la préparation de publication locale.
14. Ouvrir/exporter les preuves.
15. Quitter puis exécuter `loopforge status --format json`.

## Checkpoints

Après chaque étape : stage, acteur, next action, gates, artefact, diff, attempt et écran.

## Réussite

Le brouillon local existe, les tests passent, aucune publication réseau n'a eu lieu, toutes les gates sont explicites, l'implementation a utilisé le wrapper local existant et le run est reprenable après redémarrage.
