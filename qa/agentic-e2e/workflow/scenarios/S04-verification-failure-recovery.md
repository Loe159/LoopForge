# S04 — Vérification en échec puis récupération

1. Configurer `local-adapter-fixture` pour appliquer un patch volontairement incorrect ou activer un test fixture en échec.
2. Lancer implementation par `loopforge continue`, puis `loopforge verify`.
3. Vérifier stage Verify bloqué, check fautif visible, artefact verification présent et gate review non approuvée.
4. Reconfigurer la commande fixture pour produire le patch correct.
5. Relancer implementation selon le chemin public prévu, sans éditer l'état.
6. Relancer verification.
7. Terminer review et publication.

Réussite : l'échec est explicite, l'état est conservé et la récupération ne demande aucune édition manuelle de `run.json` ou des résultats d'attempt.
