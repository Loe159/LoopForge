---
title: "LoopForge Run — composant 6 : Plan / TODO imbriqué dans Workflow"
type: ux-component-implementation-handoff
date: 2026-10-21
status: design-approved-implementation-prepared
parent_plan: 2026-10-20-002-run-live-visual-refinement-plan.md
component: 6
implementation: tested-awaiting-user-visual-review
push: forbidden-without-explicit-request
---

# Composant 6 — Plan / TODO dans la sidebar Workflow

## Décision du 21 octobre 2026

L'utilisateur approuve la **variante B** (plan condensé / repliable), avec un ajustement prioritaire : **placer les TODO directement dans le flux Workflow, à droite, sous leur étape**, et **ne pas afficher de bloc Plan autonome dans la conversation Live**.

Exemple **fictif** à reproduire (étape et plan de la session sélectionnée) :

```text
WORKFLOW
✓ Research
✓ Planning
› Implementation                     3/5 ▾
  ✓ Inspect authentication flow
  ✓ Define validation rules
  ✓ Update token handling
  ◉ Run authentication tests
  ○ Review failure paths
○ Verification
○ Review
──────────────────────────────────────────
› Live
  Context
  Changes
  Evidences
```

Le compteur et le chevron se positionnent sur **la ligne de l'étape** pour éviter de dupliquer « Plan / TODO » dans la sidebar. Les tâches sont **indentées et visuellement subordonnées** à Implementation ; les étapes Research, Planning, Verification, Review restent au même niveau. Le compteur reflète uniquement les statuts natifs connus, jamais les transitions de l'orchestrateur. L'exemple ne signifie pas que Codex ou un autre harness expose toujours des TODO.

## Comportement proposé

- Lorsque la session/étape consultée possède un plan structuré, l'étape concernée accueille un groupe TODO. L'exemple ci-dessus illustre l'état **déplié**. Une action explicite replie les tâches et conserve `Implementation 3/5 ▸`.
- La ligne d'étape demeure navigable et sélectionnable comme aujourd'hui. Les lignes TODO sont **en lecture seule** : Enter sur une étape continue de sélectionner une étape, jamais une tâche d'agent. Ne pas ajouter de nouvelle action moteur.
- Conserver un moyen de déplier/replier au clavier **et** à la souris sans intercepter Enter de la navigation d'étape ; adapter les bindings après étude du contrat focus existant. Conserver la préférence de dépliage durant le streaming.
- Si une autre étape/session est sélectionnée, ne jamais afficher le plan de l'agent d'une session différente sous l'étape consultée. Les activités réellement en cours restent indiquées séparément par le moteur.
- Le menu `Live / Context / Changes / Evidences` reste **fixé au bas** de la sidebar, hors du scroll Workflow ; le Workflow peut défiler verticalement quand la liste s'allonge.
- Sur terminal étroit (~60/80 colonnes), le même arbre et les mêmes actions sont accessibles dans l'overlay Supervision existant, sans imposer une sidebar sur la gauche.
- Si le plan est absent, ou si la source ne permet pas de vérifier un item, omettre le groupe et ses compteurs plutôt que fabriquer une liste ou afficher `0/0`.
- Si les tâches dépassent l'espace disponible, laisser le scroll existant prendre le relais ; préserver le menu fixe, l'action requise et la barre de commande.

## Frontières des données

- Source d'autorité des **étapes** : `shell.stages` et `shell.run.current_stage` du moteur ; l'étape sélectionnée reste `snapshot.run.reading.stage_id`.
- Source des **TODO** : observations natives de la **session sélectionnée** (`snapshot.run.agent.structured_events`) lorsque `kind=plan` et une liste structurée explicite de tâches existe.
- Aujourd'hui `src/loopforge/adapters/event_store.py` reconnaît `todo_list` mais passe principalement `items` vers le corps rendu ; `src/loopforge/cli/run_projection.py` ne conserve pas un modèle typé par item pour l'arbre. Implémenter une projection bornée de `plan_items` au lieu de parser du Markdown, du JSON libre, un champ `rendered`, un transcript textuel ou les phrases de l'agent.
- Ne pas remplacer le TODO par le plan de supervision du moteur ni dériver un statut succès de l'output d'un outil.
- Mapper **uniquement** les statuts natifs reconnus, notamment completed → ✓, in_progress → ◉, pending → ○ ; états non reconnus restent neutres/non inférés. Garder le libellé et l'ordre d'origine, nettoyés pour l'affichage.
- Une mise à jour d'un même plan identifié remplace sa représentation sur place ; plusieurs plans distincts ne doivent pas être fusionnés arbitrairement. Les données bornées/provenances existantes sont conservées.
- Le résumé `3/5` est autorisé seulement si les 5 éléments et leurs statuts sont présents et fiables ; éviter compteurs partiels, faux pourcentages, chiffres du workflow ou estimations.

## Intégration technique bornée (à exécuter après clôture du Reasoning V5)

1. Ajouter le modèle typé minimal des items d'agent à la normalisation/projection (`src/loopforge/adapters/event_store.py`, puis `src/loopforge/cli/run_projection.py` ou petit module de projection isolé). Préserver le contrat des événements anciens et la compatibilité des entrées sans plan.
2. Construire un snapshot de lecture du plan pour `run_id + stage_id + session_id` sélectionnés, sans reprendre les TODO d'une tentative courante lors de la lecture d'une ancienne.
3. Ajouter une API explicite à `RunContextSidebar.update_content` pour les items et états de dépliage ; insérer les items **au sein du Workflow** et pas dans `Current activity` ou un panneau distinct.
4. Dans `src/loopforge/cli/textual_app/widgets.py`, respecter la navigation `OptionList#run-context-steps` actuelle. Approche candidate : contenu multiligne attaché à l'option de stage (une étape = une seule option), afin que les TODO ne deviennent pas des stages sélectionnables. Vérifier précisément les dimensions et la prise en charge du repli souris/clavier en Textual avant de figer cette approche ; sinon un composant d'arbre dédié doit préserver les mêmes IDs/actions d'étapes.
5. Dans `app.py`, passer les données de la session sélectionnée, gérer le repli sans side effects moteur ni confusion du focus. Ne pas changer le dispatch Enter de sélection d'étape.
6. Ajouter les styles minimalistes, indentations, contraste et fallback ASCII dans `styles.tcss` **uniquement une fois le travail Reasoning V5 finalisé**. Ne pas toucher aux sélecteurs Reasoning ou à ses styles.
7. Ajouter les tests de projection/UI et une démo Textual déterministe avec données fictives. Enregistrer la décision/résultats dans le suivi après réalisation.

## Vérifications exigées

- Tests `normalize_event(todo_list)` et projection : zéro item, libellés Unicode et longs, états completed/in_progress/pending/unknown, mises à jour partielles, ordre, événements hostiles, sessions distinctes.
- Pilot Textual : navigation entre Research, Planning, Implementation, Verification, Review sans sélection accidentelle d'un TODO ; rétention du focus pendant le streaming ; souris/clavier pour l'expansion et le repli.
- Distinction marquage actif moteur vs ligne consultée ; navigation entre anciennes tentatives et session courante, passage Live/Context/Changes/Evidences.
- Dimensions **48, 52, 60, 80, 100, 120, 160 colonnes**, hauteur ~24/30, et vue Supervision compacte ; menu des vues et commande toujours accessibles.
- Tests absence de plan, nombre de tâches variable, capture tronquée, fallback ASCII et lecture de données non fiables.
- Tests ciblés et suite complète si exécutable, compileall, git diff --check, inspection d'une capture réelle. Aucun test n'est affirmé comme exécuté par ce document.

## Frontières de concurrence

Le chantier **Reasoning V5 est déjà en cours** avec modifications locales non commitées dans `widgets.py`, `styles.tcss`, les tests et le plan principal. **Ne pas écraser, réinitialiser, mettre en stash ni mélanger ces fichiers**. Ce document est un handoff de conception isolé, pas une implémentation ni une validation runtime.

Aucun changement du code de production, aucun commit et aucun push dans cette étape de préparation. L'implémentation et sa validation visuelle sont des étapes distinctes.


## Recette technique — 21 octobre 2026

- Démonstration déterministe : `PYTHONPATH=src .venv/bin/python tools/demo_plan_todo.py` (données fictives, aucune écriture d'un run).
- Captures Textual réelles : `docs/previews/plan-todo-120-wide.svg`, `plan-todo-160-wide.svg`, `plan-todo-80-supervision.svg`. Fichiers de vérification non publiés.
- Largeurs testées : 48, 52, 60, 80, 100, 120 et 160 colonnes ; 24 et 30 lignes, repli clavier et clic sur chevron ; clic sur TODO sans navigation ; données structurées, streaming, session distincte, fallback ASCII, disparition du plan.
- Les quatre vues restent visibles en bas de la sidebar, sans doublon du plan dans Live.
- `compileall` et `git diff --check` réussis. Tests ciblés et de navigation passés ; un test historique de scroll Live a montré une instabilité de timing sur sa première exécution puis a réussi à deux nouvelles exécutions.
- `python -m unittest` complet : non conclu, environnement connecté limité dans la durée d'exécution.
- **Validation visuelle utilisateur encore attendue ; aucun push.**
