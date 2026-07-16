# S03 — Refus et correction d'approbation

1. Configurer `local-adapter-fixture` en mode nominal et aller jusqu'au plan prêt.
2. Ouvrir la confirmation puis `Esc` : aucune approbation.
3. Utiliser l'action de demande de changement si disponible, sinon rester bloqué sans exécuter implementation.
4. Reconfigurer explicitement la commande fixture en mode `revised-plan`, puis relancer le stage plan par la surface publique.
5. Vérifier qu'un nouveau plan valide est produit sans mutation du worktree.
6. Approuver explicitement.
7. Vérifier que l'implementation n'a commencé qu'après cette approbation.
8. Refaire le même contrôle pour la review : annuler, produire la review attendue puis approuver.
