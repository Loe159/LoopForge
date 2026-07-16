# Orchestration de la campagne

## Agents

| Agent | Responsabilité | Écrit dans le produit |
|---|---|---|
| `e2e-orchestrator` | Prépare, planifie, délègue, contrôle les preuves et décide du verdict | Non |
| `environment-auditor` | Vérifie Python, Git, dépendances, adaptateurs et isolation | Non |
| `journey-runner` | Exécute les parcours CLI et le workflow métier | Seulement via LoopForge |
| `textual-ui-pilot` | Teste chaque écran et modal avec Pilot | Non |
| `pty-user-runner` | Simule un utilisateur dans le vrai TUI | Seulement via LoopForge |
| `failure-injector` | Active des pannes contrôlées et vérifie la récupération | Dans les fixtures uniquement |
| `state-artifact-auditor` | Vérifie run, workspace, preuves, gates et invariants | Non |
| `regression-analyst` | Déduplique, classe et localise les défauts | Non |
| `report-writer` | Produit le rapport final | Non |

## Ordre d'exécution

### Phase 1 — Préflight

1. Créer un identifiant de campagne.
2. Relever commit, branche, OS, Python et version LoopForge.
3. Installer le paquet en editable dans un environnement propre.
4. Exécuter `python -m unittest` et `git diff --check` comme baseline.
5. Vérifier le contrat existant : `local-adapter-fixture`, `local_implementation_adapter.py`, politiques, schémas et processus isolé.
6. Exécuter un probe déterministe minimal read-only puis implementation dans une fixture jetable.
7. Vérifier les exécutables d'adapters réels sans exiger leur présence pour la suite déterministe.
8. Créer un répertoire de preuves immuable pour la campagne.

### Phase 2 — Parcours obligatoire

Exécuter séquentiellement :

1. `S00` installation et diagnostic.
2. `S01` workflow complet neuf jusqu'au brouillon local.
3. `S02` interruption puis reprise.
4. `S03` refus d'une approbation puis correction.
5. `S04` échec de vérification puis nouveau passage.

Si `S01` échoue, continuer les scénarios indépendants, mais le verdict global ne peut pas être `passed`.

### Phase 3 — Couverture étendue

Les scénarios suivants peuvent être parallélisés, chacun avec son propre `LOOPFORGE_HOME` :

- Groupe UI : `S05`, `S06`, `S07`.
- Groupe compatibilité : `S08`, `S09`.
- Groupe résilience : `S10`, `S11`, `S12`.

### Phase 4 — Audit croisé

Pour chaque scénario :

1. comparer résultat déclaré, transcript, écran final, `run.json`, artefacts et diff Git ;
2. vérifier qu'aucune gate n'a été modifiée sans action utilisateur ;
3. vérifier que les agents read-only n'ont pas modifié le worktree ;
4. vérifier que l'implementation a utilisé le wrapper local existant ;
5. vérifier que la publication reste locale ;
6. vérifier qu'un échec conserve un état reprenable.

### Phase 5 — Triage et rejeu

- Rejouer une fois chaque scénario `failed` ou `inconclusive` dans un environnement neuf.
- Marquer `flaky` si le résultat change sans modification de l'environnement déclaré.
- Fusionner les défauts ayant la même cause probable.
- Associer à chaque défaut le premier scénario, les scénarios affectés et la preuve minimale.

### Phase 6 — Verdict

Le verdict est :

- `passed` : tous les scénarios obligatoires passent, aucun `critical`, `blocker` ou `major` ouvert ;
- `passed_with_findings` : obligatoires passés, uniquement défauts `minor` ou `cosmetic` ;
- `failed` : au moins un obligatoire échoue ou un défaut `blocker/major` existe ;
- `aborted` : défaut `critical` ou environnement inexploitable.
