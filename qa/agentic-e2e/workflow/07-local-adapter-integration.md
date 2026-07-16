# Intégration avec l'adaptateur local existant

## Source de vérité

Le harnais doit s'aligner sur les composants produit suivants :

```text
src/loopforge/engine/__init__.py
src/loopforge/adapters/local_implementation_adapter.py
src/loopforge/checks/isolated_process.py
src/loopforge/checks/validate_implementation_result.py
src/loopforge/contracts/policies/local-implementation-adapter.json
src/loopforge/contracts/policies/parent-environment-isolation.json
src/loopforge/contracts/schemas/implementation-result.schema.json
```

Avant toute implémentation du harnais, l'agent lit ces fichiers et les tests qui couvrent `local-adapter-fixture`.

## Contrat à préserver

1. `local-adapter-fixture` reste un adapter supporté par le moteur.
2. Les arguments après `--` représentent directement la commande fixture, sans shell.
3. Les stages read-only exécutent cette commande avec le prompt sur stdin et contrôlent l'absence de mutation.
4. L'implementation passe par `local_implementation_adapter.py`.
5. Python n'est autorisé par le wrapper d'implementation que pour le runner fixture prévu.
6. Le workspace doit être propre avant l'attempt, hors métadonnées `.loopforge/` ignorées par la politique.
7. Le résultat d'attempt reste validé et canonique.
8. Le wrapper ne génère pas lui-même le patch, ne lance pas les checks déterministes et ne publie rien.
9. Aucun test ne modifie les politiques produit pour faciliter le scénario.

## Preuves minimales par attempt

Le scénario capture :

- commande sélectionnée et arguments ;
- `expected-session.json` ;
- `attempt.json` ;
- `adapter.stdout` et `adapter.stderr` ;
- `result.json` ;
- statut Git avant/après ;
- statut du run avant/après ;
- présence du patch uniquement après `loopforge verify` ;
- absence de demande réseau ou de publication dans le résultat.

## Oracle d'implementation

Le cas nominal est valide seulement si :

- `result.json.status == "completed"` ;
- `workspace_changed == true` ;
- `patch_generated == false` à la sortie de l'adapter ;
- `deterministic_checks_run == false` à la sortie de l'adapter ;
- `publication_requested == false` ;
- `network_requested == false` ;
- la prochaine action est la génération déterministe du patch ;
- le run devient prêt pour verification.

## Interdictions

- créer `local-adapter-fixture` comme nouvel adapter produit ;
- appeler directement `run_adapter()` depuis les scénarios de parcours ;
- écrire artificiellement `result.json` ou `run.json` ;
- contourner la commande `loopforge continue` ;
- assouplir l'allowlist ou l'isolation pour faire passer une fixture.
