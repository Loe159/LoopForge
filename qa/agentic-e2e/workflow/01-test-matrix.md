# Matrice de couverture

| Domaine | Cas nominal | Erreurs/reprise | Preuves |
|---|---|---|---|
| Installation | editable install, help, version | dépendance absente, mauvais cwd | versions, exit codes |
| Initialisation | nouveau dépôt Git | dépôt non Git, projet déjà initialisé | config, project id, registry |
| Détection pack | generic-code ou pack attendu | pack local invalide | pack effectif, explication |
| Création run | tâche manuelle | tâche vide, run déjà actif | task.md, run.json |
| Gate tâche | approuver | annuler/refuser | historique de gate |
| Research | fixture locale, artefact valide, read-only | commande absente, sortie invalide | research.md, diff vide |
| Plan | fixture locale, plan valide | demande de changement, sortie invalide | plan.md, gate plan |
| Implémentation | `local-adapter-fixture` via `local_implementation_adapter.py` | executable absent, code non zéro, annulation | attempt.json, result.json, progress.md, workspace diff |
| Vérification | checks réussis | test échoué, policy échouée | verification.md, logs |
| Review | fixture locale, rapport valide, read-only | review négative ou invalide | review.md, diff inchangé |
| Gate review | approuver | refuser puis reprendre | historique de gate |
| Publication | brouillon local | tentative réseau interdite | draft-pr.json, aucune PR distante |
| Reprise | restart du processus | opération interrompue | même run id, état cohérent |
| Textual | Home → Project → Run → Evidence | modal annulée, erreur récupérable | screen dumps, état écran |
| CLI headless | JSON/plain/script | `--no-input`, `TERM=dumb` | stdout/stderr propres |
| Multi-projet | noms distincts et identiques | déplacement/clone | registry et ids séparés |
| Historique | archive et consultation | archive annulée | artefacts conservés |
| Performance UX | navigation immédiate | opération longue/cancel | latences et événements |
