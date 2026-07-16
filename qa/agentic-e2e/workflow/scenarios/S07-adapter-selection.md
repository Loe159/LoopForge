# S07 — Sélection d'adapter

1. Définir l'adapter projet `local-adapter-fixture` via la surface publique avec la commande Python de fixture.
2. Vérifier Settings, `.loopforge/config.json` via une API de lecture, et la commande de statut.
3. Exécuter research, plan et review ; vérifier le chemin read-only isolé et le rôle demandé à chaque appel.
4. Exécuter implementation ; vérifier la création d'un attempt et le passage par `local_implementation_adapter.py`.
5. Sélectionner `kilo-code` lorsque l'exécutable est absent : blocage explicite mentionnant `kilo`, jamais `codex`.
6. Revenir à `local-adapter-fixture` et reprendre sans recréer le run.
7. Si Kilo est installé, smoke test : `ask` pour read-only, `code` pour implementation, override `--agent` prioritaire.
