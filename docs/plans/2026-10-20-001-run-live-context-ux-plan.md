---
title: "Run TUI — Live / Context / Changes / Evidences"
type: ux-implementation-plan
date: 2026-10-20
status: proposed
implementation: not-started
---

# Plan UX du Run TUI — Live, Context, Changes, Evidences

> Spécification cible (non implémentée). Le workflow, la validation, les approbations et les permissions du moteur restent inchangés. Voir [l'observation actuellement implémentée](../decisions/agent-run-observation.md) et [le design system](../../DESIGN.md).

## 1. Objectif et principes

L'utilisateur doit comprendre immédiatement **ce que l'agent fait**, **avec quelles instructions**, **quels fichiers changent** et **quelles preuves existent**. Le long System Prompt ne doit plus occuper Live. Quatre vues complémentaires : **Live** (activité condensée, déroulement chronologique), **Context** (entrées exactes et provenance), **Changes** (modifications réelles du workspace), **Evidences** (artefacts, contrôles et décisions).

La TUI reste dense, monospace, à cellules carrées, sombre et keyboard-first. La sidebar de droite conserve Metrics, Steps, Configuration et la navigation en bas. Header, champ de commandes, barre de raccourcis et panneau Required Action restent persistants. Ne pas introduire de résumé LLM supplémentaire, de deuxième agent, de permissions nouvelles ou d'actes distants.

### État confirmé du dépôt au 20 octobre 2026

Dans `src/loopforge/cli/textual_app/widgets.py`, `RunActivityFeed` affiche `System Prompt`, `Agent Output`, puis `Implementation Contract`, tandis que la sidebar présente `Changes` et `Evidences` comme indisponibles. `RunAgentOutput` contient déjà les messages, le reasoning observable et les outils repliables ; `RunToolEntry` préserve les mises à jour des appels par identifiant. `RunAgentSnapshot` expose `attempt_number`, `adapter`, `system_prompt`, `agent_output`, `implementation_contract` et `has_live_transcript`. La vue Context, les quatre vraies vues, le regroupement d'actions et les filtres Focused/All/Raw restent à développer.

## 2. Navigation et disposition

```text
┌ LoopForge / Project / Run # / Task ───────── git:branch  Status ┐
│ ┌ MAIN ─────────────────────────┐ ┌ RUN CONTEXT ─────────────┐ │
│ │ Stage · Attempt · Harness     │ │ Metrics                  │ │
│ │ Live / Context / Changes /…  │ │ Steps                    │ │
│ │                              │ │ Configuration            │ │
│ │ [active view, scrollable]    │ │                          │ │
│ │                              │ │ Live                     │ │
│ │ [Required Action if needed]  │ │ Context                  │ │
│ │ [Command Input]              │ │ Changes                  │ │
│ └──────────────────────────────┘ │ Evidences                │ │
│                                  └──────────────────────────┘ │
└ contextual hotkeys ────────────────────────────────────────────┘
```

Le contexte sélectionné est **project_id + run_id + stage + attempt + session**. Un sélecteur d'attempt permet de consulter les essais précédents sans croiser leurs logs, prompts, preuves ou diffs. Si aucune tentative n'existe : `No attempt yet`. Ne pas confondre numéro de run et numéro d'attempt. L'onglet sélectionné ne modifie aucune autorité moteur.

Navigation : flèches + Enter sur les quatre vues, Tab vers les accordéons, Enter pour détailler, Esc pour revenir. Les renvois `View context`, `View changes`, `View evidence` conservent l'identité d'exécution. Inspecter les raccourcis existants avant de nouveaux bindings. Étroits (60/80 colonnes) : sidebar masquée et barre de vues compacte accessible au clavier ; larges (120/160) : sidebar fixe à droite. Toujours préserver le champ de commandes et la lecture du flux.

## 3. Live : flux d'exécution

### 3.1 Modes de lecture

- **Focused** (défaut) : événements importants seulement, regroupements compacts, erreurs/gates/résultats toujours visibles.
- **All** : événements **structurés réellement observés**, ordre chronologique exact, détails consultables, pas de perte d'événement.
- **Raw** : journal original de l'attempt, avec source, troncature et limites visibles. Le flux ANSI du terminal natif n'est pas une source typée.

Le mode change l'affichage, jamais le processus ni les données conservées.

### 3.2 Composants du flux (tous repliables si pertinent)

| Composant | Résumé par défaut | Ouverture et source |
| --- | --- | --- |
| **Stage / Attempt** | `Research · Attempt 01 · Codex` | Phase, identité, état, dates si connues. |
| **Agent initialized** | `Researcher · Read-only` + `View context` | Statut réel de l'observation, pas de prompt intégral. |
| **Agent message** | Texte public court sans paraphrase inventée | Message complet réel. |
| **Reasoning** | `Reasoning available` (fermé) | Seulement thinking effectivement exposé par le harnais. |
| **Plan / TODO** | Nombre et statut si donnés par le harnais | Items natifs ; sinon message ordinaire. |
| **Exploration** | `4 reads · 2 searches` si classés avec certitude | Fichiers, recherches, outils originaux, IDs. |
| **Tool call/result** | `Shell · pytest` + statut | Arguments, sortie, exit code, Call ID, durée si réellement mesurée. |
| **File changes** | `3 files changed` si établi | Chemins, opérations, lien Changes, diff Git. |
| **Verification** | Commande et résultat prouvé | Comptage de tests seulement si parsé de sortie fiable ; ne pas inférer à partir d'exit 0. |
| **Warning / error / blocker** | Toujours visible et prioritaire | Cause connue, source, récupération autorisée par le moteur. |
| **Final answer / artifact** | `research.md produced` si extrait | Contenu produit, lien Evidences. |
| **Contract validation** | Valid / invalid selon le validateur LoopForge | Champs manquants, raison, reçus. |
| **Attempt completion** | Completed / failed / cancelled / unknown | Résultat moteur, prochaine action réelle. |

Les appels de lecture/recherche consécutifs peuvent être regroupés **sans supprimer les événements originaux**. Ne jamais cacher une erreur, un refus, une demande d'approbation ou une transition d'étape au sein d'un groupe. Un appel start/result garde le même Call ID ; des outils homonymes parallèles restent distincts. Si résultat absent après l'arrêt : `unknown`, jamais vert par défaut. Reasoning chiffré, masqué ou absent : ne pas deviner.

Auto-follow seulement au bas du flux. Scroll manuel, ouverture d'un outil ou changement de vue désactive le suivi jusqu'à `Follow live`. Préserver état des accordéons, focus, sélection et clés stables pendant streaming et reprise.

**Research read-only** : messages, lectures, recherches et `research.md`, sans fausse carte de modifications. **Implementation** : modifications et tests seulement si établis. **Human gate** : Required Action via état moteur, pas via texte de l'agent. **Observation indisponible** : avertissement explicite et renvoi au terminal natif.

## 4. Context : snapshot exact fourni à l'agent

Une page en lecture seule par **stage + attempt**. Sommaire immédiatement visible : objectif, rôle, harnais, pack, permissions **effectives** si vérifiables, artefact attendu. Le raw prompt envoyé reste accessible et identique à la source enregistrée (des secrets peuvent imposer une redaction à l'affichage, signalée).

| Section | Exemple réel du Research prompt présenté | Défaut |
| --- | --- | --- |
| **Mission & Role** | `Objective: test`, agent `researcher` | Résumé ouvert |
| **System Instructions** | `LoopForge Research Stage`, format de sortie et règles du rôle | Repliée |
| **Injected Documents** | `task.md`, `loop.md`, `memory.md` et sections internes | Repliée, nombre |
| **Environment & Git** | Run dir, workspace, repository, branche, base commit | Repliée |
| **Pack, Skills & Tools** | Pack `python`, `patch-review`, `python-testing`, `python-packaging` | Repliée |
| **Permissions & Security** | Commands bounded, filesystem read, git actions, network deny, publication deny | Résumé effectif visible |
| **Output Contract** | `research.md`, frontmatter, required sections | Résumé visible |
| **Validation & Limits** | Success checks, max 3 attempts, timeout 1800 s, stagnation, rollback et human review | Repliée |
| **Raw Prompt** | Markdown exact transmis | Fermé par défaut |

Les intitulés `Paths`, `Objective`, `Required Artifact`, `Required Sections`, `Embedded Run Inputs`, `Permission Boundary`, `Pack Agent Instructions` du prompt actuel alimentent ces catégories. Les sections vides restent marquées « non spécifié » seulement si utiles ; pas de panneaux vides décoratifs.

**Distinction fondamentale :** `loop.md` peut déclarer des outils en écriture et pourtant la phase Research peut être restreinte effectivement à read-only. Afficher `Declared in document` séparément de `Enforced by runner`. Les documents injectés, y compris mémoire et texte fourni par l'utilisateur, n'héritent pas artificiellement d'une autorité supérieure parce qu'ils apparaissent dans le prompt.

### Données de Context : approche sans LLM

Le générateur de prompt doit fournir à la fois (a) le raw effectivement envoyé et (b) un **manifeste structuré** reflétant ses sections, sources, niveaux d'autorité, hashes et références internes bornées. Projet de modèle versionné :

```json
{
  "schema_version": 1,
  "run_id": "...",
  "stage": "research",
  "attempt_number": 1,
  "adapter": "codex",
  "raw_prompt_ref": "relative-run-artifact",
  "raw_prompt_sha256": "...",
  "capture_state": "complete",
  "sections": [
    {
      "id": "mission",
      "source": "task.md",
      "authority": "task-input",
      "summary": "test",
      "content_ref": "relative-snapshot-artifact"
    }
  ]
}
```

Chemins confinés sous la racine autorisée, références contrôlées. Sources possibles : `engine-policy`, `pack-instruction`, `task-input`, `project-memory`. La provenance n'octroie **aucune permission**. Anciens runs : parser Markdown best-effort **marqué partial/derived**, jamais présenté comme capture originale ; si le prompt manque, afficher l'indisponibilité sans le régénérer.

## 5. Changes : travail réel, pas intention

Vue alimentée en priorité par l'état Git/worktree, patches et snapshots de l'attempt ; un log `Write file` n'est pas preuve de modification. Résumé : modifiés/ajoutés/supprimés, +/− calculés, base commit, statut du workspace. Liste des chemins relatifs avec statuts ; ouverture en diff coloré borné et paginé, gestion binary/rename/troncature. Distinguer **delta par attempt** et **delta cumulatif du workspace**. Les artefacts externes (research.md, plan.md…) appartiennent à Evidences. En lecture seule, `No workspace changes expected`, et violation explicite si détectée. Aucune action destructive Apply/Discard/Rollback sans chemin moteur confirmé.

## 6. Evidences : preuves et décisions

Lister `research.md`, `plan.md`, `verification.md`, `review.md`, résultats de checks, contrats finaux, reçus de gates humains, et artefact de publication **local**, selon l'étape. Métadonnées : origine, stage/attempt, date/hash si disponible, validation, chemin sûr, ouverture lecture seule.

Cinq niveaux **jamais fusionnés** :
1. **Agent output** : l'agent déclare un résultat ;
2. **Artifact extracted** : LoopForge a enregistré l'artefact ;
3. **Contract validated** : validateur officiel passé/échoué ;
4. **Deterministic verification** : preuves indépendantes ;
5. **Human decision** : approbation/refus réellement enregistrés.

Un `research.md` produit mais invalide ne devient pas un run réussi. Des tests verts n'accordent pas d'approbation. `adapter.stdout` et `agent-transcript.log` restent diagnostics, jamais preuves de validation ou publication.

## 7. Sources réelles et modèle d'événements

Transport actuel : [docs/decisions/agent-run-observation.md](../decisions/agent-run-observation.md). Codex interactif : hooks + messages/reasoning publics de la session exacte, headless `exec --json`. Kilo/OpenCode : plugin `message.part.updated` (`text`, `reasoning`, `tool`), headless `run --format json --thinking`. Claude : hooks et texte/thinking publics selon disponibilité. Aider/mini-SWE-agent : fallback texte lisible **sans classification fictive**. Les schémas de transcript natifs peuvent évoluer.

La projection UI, dérivée et versionnée, devrait porter : `event_key`, `run_id`, `stage`, `attempt`, `source`, `kind`, `status`, `title`, `preview`, `detail_ref`, `call_id`, `parent_id` si fourni, `occurred_at` si fourni, `order`, `truncated` et `provenance`. Éviter les heures, résumés, métriques et associations d'outils inventés. Source d'autorité par domaine : **moteur** pour workflow et approvals, **Git** pour changes, **validateur** pour evidence, **harnais** pour messages/outils. Conserver les formats `agent-transcript.log` et `adapter.stdout` pour compatibilité.

## 8. Comportements transversaux

Sécurité : lier tout événement à la session/attempt exact ; lire toute sortie d'agent comme donnée non fiable, affichage littéral, redaction et bornes ; chemins sous racines autorisées ; signaler les prompts/traces locaux sensibles ; pas de fuite dans les aperçus compacts. Performances : parser borné, projections déterministes, rendu incrémental sans remonter toute la vue, diff chargé à l'ouverture. UI : clavier et souris, pas de couleur comme unique statut, compatibilité ASCII, états `pending/running/completed/failed/blocked/cancelled/interrupted/unknown`.

La navigation ne doit modifier ni actions ni états moteur. `Required Action` reste le seul endroit des décisions importantes avec ciblage explicite, contrat examiné et approbation enregistrée.

## 9. Maquettes et scénarios à valider

Produire quatre maquettes de base : **Running (Focused)**, **Tool expanded**, **Completed (résultat + validation)**, **Blocked (Required Action)**. Tester aussi : démarrage sans attempt ; Research read-only ; planning en attente d'approbation ; tests échoués ; plusieurs attempts ; appels d'outils parallèles identiques ; observation indisponible ; journal tronqué ; session terminée sans résultat d'outil ; mauvaise tentative sélectionnée ; violation read-only ; terminal 60/80/120/160 colonnes ; scroll pendant le streaming ; reprise après fermeture.

Maquette textuelle indicative (fictive) :

```text
--- Research · Attempt 01 · Codex ---
✓ Agent initialized · Researcher · Read-only [Context →]
✓ Exploration                      4 reads · 2 searches [>]
  Agent: Inspected relevant files and tests.
✓ research.md extracted                         [Evidences →]
✓ Contract validation: passed
```

Ne pas suggérer que l'agent a réussi tant que le validateur officiel ne l'a pas constaté.

## 10. Phases d'implémentation et acceptation

### A — Inventaire et tests de caractérisation
Confirmer les sources réelles des snapshots, prompts, permissions, worktrees, artifacts et observation pour chaque harnais. Fixer l'identité run/stage/attempt/session et une fixture par mode. **Critère :** aucune donnée absente n'est convertie en réussite ou en permission.

### B — Navigation 4 vues
Mettre en place sélection persistante, sidebar interactive et fallback compact, vues même vides, liens croisés et préservation de Command Input et Required Action. **Critère :** naviguer sans exécuter d'action et sans perte de focus/scroll au retour.

### C — Context structuré
Générer et conserver manifeste + raw prompt identique, snapshot par attempt, provenance, distinctions enforced/declared, et fallback historiques. **Critère :** comparaison hash/raw exacte, aucune lecture hors racine, absence d'association incorrecte à un autre attempt.

### D — Live Focused/All/Raw
Réutiliser le journal observé, introduire classification déterministe, grouping réversible, cartes d'erreur, outil, reasoning, livrable et validation, états inconnus et follow contrôlé. **Critère :** événements comptés sans perte ; Call IDs parallèles corrects ; aucune réussite inférée.

### E — Changes / Evidences
Brancher les états Git/diffs et les artefacts moteur/contrôles/gates ; lecture seule et liens croisés. **Critère :** modifications réellement constatées, distinction preuve/approval, aucune mutation implicite.

### F — Tests de bout en bout et revue UX
Pilotes Textual, fixtures Codex et Kilo, tests de streaming/reprise/resize/ASCII/permissions, tests moteur existants, validation visuelle des quatre variantes. **Critère final :** tous les scénarios de §9 passent ; données vérifiables ; moteur et CLI inchangés ; absence de prompt intégral dans Live.

### Zones de code candidates (pas des changements déjà faits)

- `src/loopforge/cli/textual_app/widgets.py`, `app.py`, `run_presenter.py`, `styles.tcss` ;
- `src/loopforge/cli/models.py` et `state_store.py` ;
- générateur de prompts, stockage des artefacts, lecture du worktree et observation ;
- `tests/test_run_transcript_ui.py` et tests UI/Pilot, d'observation et d'autorité moteur.

Décisions ouvertes à trancher **avant de coder** : emplacement du sélecteur d'attempt, raccourcis disponibles, forme versionnée du manifeste et politique de redaction du raw, granularité du grouping à 60 colonnes. La séparation Live/Context/Changes/Evidences et la préservation intégrale du prompt original sont acquises.
