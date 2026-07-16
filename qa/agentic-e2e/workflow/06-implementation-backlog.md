# Backlog minimal pour rendre le workflow exécutable

## Déjà disponible dans LoopForge

Ne pas réimplémenter :

- l'adapter `local-adapter-fixture` ;
- `src/loopforge/adapters/local_implementation_adapter.py` ;
- l'isolation des processus ;
- la validation du résultat d'implementation ;
- les attempts, workspaces, artefacts et transitions existantes.

## P0 — indispensable

1. Ajouter une commande fixture Python déterministe compatible avec `local-adapter-fixture`, capable de répondre aux stages read-only et implementation.
2. Ajouter une factory de dépôt fixture Python avec tests rapides et patch attendu.
3. Ajouter un runner de scénario qui crée un `LOOPFORGE_HOME` isolé et journalise chaque action.
4. Ajouter des helpers Textual : attente de snapshot, attente de fin d'opération, dump d'écran et dump d'état.
5. Ajouter le scénario `S01` comme test principal de workflow complet.
6. Ajouter l'audit des invariants de gates, artefacts, worktree, attempts et publication locale.
7. Ajouter un test de contrat qui prouve que l'implementation passe par `local_implementation_adapter.py` et que les stages read-only restent read-only.
8. Générer `result.json` et `final-report.md`.

## P1 — couverture de reprise

1. PTY réel multiplateforme Linux/Windows.
2. Scénarios d'annulation, executable fixture absent, vérification en échec et reprise.
3. Parcours multi-projet et même basename.
4. Sorties JSON/plain/ASCII/NO_COLOR.
5. Rejeu automatique des échecs et classification des flakes.
6. Modes fixture `invalid-artifact`, `nonzero-exit`, `slow`, `partial-write` et `out-of-scope-patch`.

## P2 — approfondissement

1. Mesure des latences de navigation et détection des opérations bloquantes.
2. Injection de corruption contrôlée de fichiers d'état copiés, jamais du dépôt réel.
3. Smoke tests d'adapters réels installés.
4. Export JUnit/JSON pour CI.
5. Commande produit éventuelle `loopforge test-e2e`, sans lier le harnais au moteur de workflow.

## Critère de livraison initiale

La première version est suffisante lorsque `S01` peut être lancée par une commande, atteint le brouillon local avec `local-adapter-fixture`, prouve le passage par le wrapper d'implementation existant et produit un rapport permettant de localiser toute étape bloquante.
