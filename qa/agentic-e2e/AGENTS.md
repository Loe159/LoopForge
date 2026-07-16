# Règles générales des agents de validation LoopForge

## Mission

Tester LoopForge comme un utilisateur, recueillir des preuves reproductibles et produire un rapport exploitable. Les agents de test ne corrigent pas le produit pendant la campagne.

## Règles impératives

- Lire le `AGENTS.md` racine du dépôt et les documents `docs/agent/00-overview.md`, `docs/agent/06-build-test-run.md` et `docs/cli-ux-command-plan.md`.
- Utiliser uniquement les interfaces publiques : binaire `loopforge`, façade `loopforge.cli`, `LoopForgeApp.run_test()`, fichiers d'artefacts documentés et APIs de lecture du moteur.
- Réutiliser `local-adapter-fixture` et `src/loopforge/adapters/local_implementation_adapter.py`; ne créer aucun adaptateur parallèle.
- Ne jamais écrire manuellement un statut, une approbation ou un champ de cycle de vie dans `run.json`.
- Utiliser un dépôt fixture, un `LOOPFORGE_HOME` et un workspace distincts pour chaque scénario.
- Ne jamais exécuter un scénario destructif dans le dépôt LoopForge réel.
- Capturer les commandes, entrées, sorties, écrans, artefacts et états nécessaires pour reproduire chaque résultat.
- Masquer les secrets, chemins personnels et jetons avant d'écrire les preuves.
- Ne pas déclarer un succès parce qu'une commande retourne `0` : vérifier les effets attendus.
- Ne pas déclarer un échec uniquement sur le texte ou la couleur : vérifier l'état et les artefacts.
- Un scénario en échec est rejoué une fois dans un environnement neuf pour distinguer défaut reproductible et flake.
- Les agents d'exécution ne modifient pas le code produit. Seul un workflow séparé de correction peut utiliser le rapport.

## Gravité

- `critical` : perte/corruption de données, contournement de gate, écriture hors workspace, publication réseau inattendue.
- `blocker` : impossible de terminer le workflow principal.
- `major` : fonctionnalité importante cassée avec contournement manuel possible.
- `minor` : défaut localisé sans blocage.
- `cosmetic` : présentation uniquement.

## États d'un scénario

`passed`, `failed`, `blocked`, `skipped`, `flaky`, `inconclusive`.

## Condition de fin

La campagne s'arrête immédiatement sur un défaut `critical`. Les autres défauts sont collectés afin d'obtenir un audit complet.
