# Validation agentique de bout en bout de LoopForge

Ce dossier définit un système de test piloté par agents pour valider LoopForge comme le ferait un utilisateur réel, depuis une installation propre jusqu'à la préparation locale d'un brouillon de publication.

## Objectif

Détecter en une seule campagne les erreurs qui empêchent un workflow complet : navigation Textual, commandes CLI, sélection d'adapter, validations humaines, reprise après interruption, génération des artefacts, modification du workspace, vérification, review et publication locale.

Le système ne remplace pas les tests unitaires existants. Il ajoute trois niveaux complémentaires :

1. **Pilot Textual** : interactions rapides avec `App.run_test()` et `Pilot`.
2. **CLI réel** : commandes non interactives dans un environnement isolé.
3. **PTY réel** : lancement du véritable binaire `loopforge` dans un pseudo-terminal avec saisies clavier.

## Adaptateur déterministe déjà disponible

Le workflow ne crée pas un nouvel adaptateur. Il réutilise les chemins produit existants :

- l'adapter public `local-adapter-fixture`, déjà déclaré par le moteur ;
- `src/loopforge/adapters/local_implementation_adapter.py` pour l'étape d'implémentation ;
- `src/loopforge/checks/isolated_process.py` pour les étapes read-only ;
- les politiques et schémas existants sous `src/loopforge/contracts/`.

Le harnais doit seulement fournir une commande Python de fixture déterministe. Cette commande reçoit le prompt LoopForge, produit les artefacts read-only attendus ou applique le petit patch prévu dans le workspace. Ainsi, un échec du parcours obligatoire indique un problème LoopForge ou du harnais, et non une variation d'un LLM.

Un smoke test séparé peut ensuite utiliser un adapter réel installé localement.

## Emplacement dans le dépôt

```text
qa/agentic-e2e/
  AGENTS.md
  workflow/
  agents/
  skills/
  schemas/
  templates/
```

Ce dispositif est un **harnais de validation externe**. Il ne crée pas un second moteur de workflow, ne modifie pas directement les états de run et ne contourne aucune gate. Toutes les transitions passent par les commandes et actions publiques de LoopForge.

## Lancement conceptuel

```text
python -m qa.agentic_e2e run --suite mandatory
python -m qa.agentic_e2e run --suite extended
python -m qa.agentic_e2e run --scenario S01
```

Le runner de campagne reste à implémenter. L'adaptateur local et son contrat d'exécution existent déjà et doivent être réutilisés, pas remplacés. Le contrat attendu du harnais est détaillé dans `workflow/00-orchestration.md`, `workflow/05-execution-policy.md`, `workflow/06-implementation-backlog.md` et `workflow/07-local-adapter-integration.md`.

## Résultats attendus

Chaque campagne produit :

```text
artifacts/e2e/<campaign-id>/
  campaign.json
  environment.json
  scenarios/<scenario-id>/result.json
  scenarios/<scenario-id>/transcript.txt
  scenarios/<scenario-id>/screen-dumps/
  scenarios/<scenario-id>/state-before.json
  scenarios/<scenario-id>/state-after.json
  findings.json
  final-report.md
```

Une campagne réussit seulement si le scénario principal `S01` atteint la publication locale, si les invariants de sécurité sont respectés et si aucun défaut bloquant ou critique n'est ouvert.
