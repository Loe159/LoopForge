# S02 — Interruption et reprise

1. Créer un run et aller jusqu'au plan approuvé.
2. Configurer `local-adapter-fixture` avec la commande fixture en mode `slow`.
3. Démarrer implementation.
4. Envoyer Ctrl+C pendant l'opération.
5. Vérifier « Operation cancelled », TUI toujours actif et gate inchangée.
6. Quitter LoopForge.
7. Relancer `loopforge`, retrouver le même projet et le même run.
8. Reconfigurer la même commande fixture en mode nominal.
9. Relancer implementation puis terminer le workflow.

Réussite : aucun run dupliqué, état cohérent, aucun processus résiduel, attempt interrompu traçable et workflow terminable.
