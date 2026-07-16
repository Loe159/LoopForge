# S00 — Installation et diagnostic

## But

Prouver que LoopForge est installable et que les erreurs suivantes ne viennent pas d'un environnement non identifié.

## Actions

1. Créer un venv et installer `pip install -e .`.
2. Exécuter `loopforge version`, `loopforge --help`, `loopforge pack list`.
3. Exécuter baseline unittest et diff check.
4. Vérifier que `local-adapter-fixture` est supporté et que `local_implementation_adapter.py` correspond à sa politique.
5. Initialiser une fixture Git avec un `LOOPFORGE_HOME` neuf.
6. Exécuter un stage read-only avec la commande fixture et prouver un diff vide.
7. Exécuter une implementation nominale via `loopforge continue --adapter local-adapter-fixture -- ...` et vérifier les artefacts d'attempt.
8. Vérifier que `loopforge` ouvre le TUI dans un PTY et que Ctrl+C quitte.

## Réussite

Toutes les commandes obligatoires répondent sans traceback, la version est identifiable, l'isolation est prouvée et le chemin adaptateur existant fonctionne sans modification de politique.
