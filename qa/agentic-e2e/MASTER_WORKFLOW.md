# Workflow maître de validation LoopForge

Ce document est le point d'entrée de la campagne. Les fichiers spécialisés sont la source de vérité et doivent être lus dans cet ordre.

## 1. Cadre général

1. `README.md` — objectif, niveaux de test, emplacement et résultats.
2. `AGENTS.md` — règles communes, limites et gravités.
3. `workflow/00-orchestration.md` — agents, phases et verdict global.
4. `workflow/01-test-matrix.md` — couverture fonctionnelle.
5. `workflow/02-screen-routes.md` — parcours Home, Project, Run, Evidence, Settings et modales.
6. `workflow/03-invariants.md` — sécurité, autorité, persistance et UX.
7. `workflow/04-reporting.md` — preuves, findings et rapport final.
8. `workflow/05-execution-policy.md` — isolation, timeouts et commande fixture.
9. `workflow/06-implementation-backlog.md` — éléments restant à implémenter dans le harnais.
10. `workflow/07-local-adapter-integration.md` — intégration obligatoire avec l'adaptateur local existant.

## 2. Adaptateur obligatoire

Le parcours déterministe doit utiliser :

- l'adapter public `local-adapter-fixture` ;
- le chemin read-only isolé existant pour research, plan et review ;
- `src/loopforge/adapters/local_implementation_adapter.py` pour implementation.

Il est interdit de créer un adapter concurrent ou de modifier les politiques produit pour faciliter les tests.

## 3. Ordre des scénarios

Suite obligatoire, séquentielle :

1. `S00-preflight.md` ;
2. `S01-full-happy-path.md` ;
3. `S02-interrupt-resume.md` ;
4. `S03-approval-rejection.md` ;
5. `S04-verification-failure-recovery.md`.

Suite étendue, isolable et parallélisable : `S05` à `S12`.

## 4. Agents

L'orchestrateur délègue aux agents documentés sous `agents/`. Chaque agent lit son propre `AGENTS.md`, les règles communes et uniquement les skills nécessaires sous `skills/`.

## 5. Condition de réussite

La campagne réussit uniquement si `S01` atteint le brouillon de publication locale, si tous les scénarios obligatoires passent, si aucune gate n'est contournée, si aucune publication réseau n'a lieu et si aucun finding `critical`, `blocker` ou `major` reste ouvert.
