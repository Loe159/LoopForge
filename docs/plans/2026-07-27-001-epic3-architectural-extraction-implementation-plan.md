---
title: "Epic 3/6 — Architectural extraction: implementation plan"
type: implementation-plan
date: 2026-07-27
topic: epic3-architectural-extraction
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/29
artifact_contract: implementation-plan/v1
artifact_readiness: final
execution: code
---

# Epic 3/6 — Architectural Extraction: Implementation Plan

## Goal Capsule

- **Objective:** remplacer l'implémentation monolithique et dupliquée par des services de domaine typés et une couche de commandes applicatives unique, tout en préservant la compatibilité publique pendant la migration.
- **Parent roadmap:** [LoopForge 1.0 product hardening](2026-07-22-001-refactor-loopforge-product-hardening-plan.md)
- **GitHub epic:** [#29](https://github.com/Loe159/LoopForge/issues/29)
- **Depends on:** Epic 2 (schémas persistants figés, lifecycle transitions, `ActionScope`, process receipts, effective-pack contract)
- **May overlap with:** Epic 4 (après freeze des contrats partagés)
- **Duration estimate:** 4 à 5 semaines (une personne) / 3 à 4 semaines (deux personnes)
- **Exit gate:** chaque action mutante atteint une seule implémentation de commande applicative ; aucun renderer ou worker Textual ne mute lifecycle/persistence ; dépendances de domaine acycliques ; suites de tests indépendantes et exécutables

---

## Context

### Current state on `master`

**Monolithic core:**
- `src/loopforge/engine/__init__.py` — **8 913 lignes**, 100+ fonctions. Ce module contient lifecycle, persistence, Git, workspaces, packs, subprocess, memory, metrics, installation, et rendu.
- `src/loopforge/cli/interactive.py` — **2 250 lignes**. Reproduit des parcours déjà présents dans les handlers top-level.
- `src/loopforge/cli/__init__.py` — **1 512 lignes**. Facade CLI et dispatch.

**Extractions déjà entamées (Phases 0-2):**
- `engine/lifecycle.py` — machine à états typée (667 lignes)
- `engine/path_resolvers.py` — validation de confinement des chemins (56 lignes)
- `engine/process_runner.py` — runner borné avec `ProcessReceipt` (407 lignes)
- `engine/repositories.py` — repositories avec verrou et CAS (142 lignes)
- `engine/locking.py` — verrous inter-processus cross-platform (308 lignes)
- `engine/recovery.py` — quarantaine de fichiers corrompus (44 lignes)
- `engine/doctor.py` — service de diagnostic unifié (577 lignes)
- `engine/git_state.py` — read models Git (230 lignes)
- `engine/storage.py`, `engine/projects.py`, `engine/indexes.py`, `engine/packs.py`, `engine/metrics.py` — préexistants
- `engine/models/` — quasi vide (1 ligne dans `__init__.py`, `migrations.py` et `schema.py` existent)

**Code restant dans le monolithe (par section):**

| Lignes | Section | Domaine cible |
|---|---|---|
| 1293-1810 | Installation, utilitaires | `engine/installation.py` |
| 1986-2439 | Profils, initialisation, config | `engine/project_service.py` |
| 1152-1411, 6156-6517 | Workflow state, approbations | `engine/workflow.py` |
| 1414-1497, 2832-3339 | Templates, mémoire, `learn_run` | `engine/memory.py` |
| 1831-1979 | Artifacts, parsing frontmatter | `engine/artifacts.py` |
| 5042-5558 | Création et résumé de runs | `engine/run_service.py` |
| 5567-6140, 7131-7707 | Attempts, exécution d'adapter | `engine/execution.py` |
| 6665-7127 | Readonly stages, publication | `engine/stages.py` |
| 7752-8250 | Vérification, pack checks | `engine/verification.py` |
| 3342-4179, 8708-8913 | Status, guidance, continue | `engine/status_service.py` |
| 2441-2659 | Workspace, Git preflight | `engine/workspace.py` |

**Triple duplication de comportement:**
- Commandes top-level : `cli/workflow.py`, handlers dans `cli/__init__.py`
- Commandes slash : `cli/interactive.py` — parcours dupliqués
- Actions TUI : `cli/textual_app/app.py` — appels directs à l'engine

**Accès problématiques identifiés:**
- `cli/interactive.py:2125` — `from loopforge.engine import _pack_registry` (privé)
- `cli/textual_app/app.py:208` — `from loopforge.engine import resume_run` (bypass handler)
- `cli/state_store.py:67` — `from loopforge.engine import current_status` (bypass handler)

---

## Target Architecture

```
flowchart TB
  CLI["Top-level CLI"] --> AC["Application commands"]
  SH["Slash shell"] --> AC
  TUI["Textual UI"] --> AC
  AC --> LF["Stable loopforge.engine facade"]
  LF --> SM["Lifecycle state machine"]
  LF --> RR["Versioned repositories"]
  LF --> WS["Transactional workspace service"]
  LF --> PC["Frozen effective pack contract"]
  LF --> PR["Bounded process runner"]
  LF --> VS["Verification service"]
  RR --> JS["Locked atomic JSON storage"]
  SM --> RR
  PC --> VS
  PR --> VS
  AC --> RM["Immutable read models"]
  RM --> TUI
```

La façade `loopforge.engine` reste le point de compatibilité, mais cesse d'être le lieu de toutes les implémentations. Les mutations passent par les commandes applicatives et les lectures UI par des read models immuables.

---

## Subtasks

---

### Subtask 0 — Audit et baseline (1-3 jours)

**Objective:** Établir l'état réel du code avant extraction. Cartographier ce qui a déjà été migré vs ce qui reste dans le monolithe. Documenter la baseline de tests.

**Files concerned:**
- `src/loopforge/engine/__init__.py` — audit complet fonction par fonction
- `src/loopforge/engine/*.py` — vérifier non-duplication
- `src/loopforge/cli/*.py` — cartographie des imports vers `loopforge.engine`

**Steps:**

#### 0.1 Cartographie du monolithe
- Lister chaque fonction/classe dans `__init__.py` : nom, lignes, domaine logique
- Pour chaque sous-module déjà extrait : vérifier que `__init__.py` ne contient pas de duplicata
- Identifier les fonctions à migrer vers sous-module existant vs nouveau module

#### 0.2 Baseline de tests
- Exécuter `python -m unittest` : succès, échecs, erreurs
- Exécuter chaque suite individuelle
- Documenter dans `docs/decisions/003-epic3-baseline.md`

#### 0.3 Cartographie des dépendances
- Documenter les 61 imports `loopforge.cli.*` → `loopforge.engine`
- Marquer les accès problématiques (privés, bypass handlers)
- Lister les imports candidats au remplacement par commandes applicatives

**Validation:** Document `docs/decisions/003-epic3-baseline.md` produit.

---

### Subtask 1 — Modèles typés et versionnés (3-5 jours)

**Objective:** Introduire des dataclasses typés aux frontières. Chaque modèle rejette les champs inconnus. Couvre R16, R17.

**Files concerned:**
- `src/loopforge/engine/models/__init__.py` — peuplement
- Nouveaux fichiers dans `engine/models/`
- `tests/test_models.py` — nouveau

**Modèles à créer:**

| Modèle | Fichier | Source actuelle |
|---|---|---|
| `ProjectConfig` | `engine/models/project.py` | `new_config()`, `normalize_config()` |
| `RunState` | `engine/models/run.py` | `run.json` |
| `LifecycleTransition` | `engine/models/lifecycle.py` | `lifecycle.py` |
| `ActionScope` | `engine/models/scope.py` | Déjà un dataclass dans `__init__.py` |
| `EffectivePackContract` | `engine/models/pack.py` | `packs.py` |
| `VerificationResult` | `engine/models/verification.py` | `verify_run()` |
| `AppCommandResult` | `engine/models/commands.py` | Nouveau |
| `AppCommandError` | `engine/models/commands.py` | Nouveau |
| `StageArtifact` | `engine/models/artifacts.py` | `parse_frontmatter()` |

**Règles de validation:**
- `from_dict()` lève `ValueError` sur champs inconnus (pas de silent ignore)
- `to_dict()` explicite et versionné
- `schema_version` obligatoire sur modèles persistants

**Validation:** `tests/test_models.py` — validation, round-trip, rejet ; pas de régression.

---

### Subtask 2 — Extraction incrémentale des domaines (8-12 jours)

**Objective:** Extraire le monolithe un domaine à la fois, façade `loopforge.engine` stable. Chaque extraction = 1 PR vert. Couvre R16.

**Principe par extraction:**
1. Tests de caractérisation avant déplacement
2. Déplacer le code → sous-module
3. Réexport depuis `engine/__init__.py`
4. `python -m unittest` passe
5. `python -m loopforge version --json` fonctionne

**Extractions planifiées (11 modules + nettoyage final):**

| # | Domaine | Nouveau module | Lignes ~ |
|---|---|---|---|
| 2.1 | Installation & utilitaires | `engine/installation.py` | 1293-1810 |
| 2.2 | Profils & initialisation projet | `engine/project_service.py` | 1986-2439 |
| 2.3 | Workflow state & approbations | `engine/workflow.py` | 1152-1411, 6156-6517 |
| 2.4 | Templates & mémoire | `engine/memory.py` | 1414-1497, 2832-3339 |
| 2.5 | Artifacts & parsing | `engine/artifacts.py` | 1831-1979 |
| 2.6 | Création & résumé de runs | `engine/run_service.py` | 5042-5558 |
| 2.7 | Attempts & exécution adapter | `engine/execution.py` | 5567-6140, 7131-7707 |
| 2.8 | Readonly stages & publication | `engine/stages.py` | 6665-7127 |
| 2.9 | Vérification | `engine/verification.py` | 7752-8250 |
| 2.10 | Status, guidance, list runs | `engine/status_service.py` | 3342-4179, 8708-8913 |
| 2.11 | Workspace & Git preflight | `engine/workspace.py` | 2441-2659 |
| 2.12 | Nettoyage final | `__init__.py` < 200 lignes | — |

**Validation:** même nombre succès/échecs ; `version --json` OK ; `git diff --check` propre.

---

### Subtask 3 — Commandes applicatives unifiées (5-8 jours)

**Objective:** Couche de commandes applicatives unique. Supprimer la duplication top-level/slash/TUI. Couvre R18, R19.

**Files concerned:**
- `src/loopforge/commands/` — nouveau package (12 modules)
- `src/loopforge/cli/__init__.py` — adaptation
- `src/loopforge/cli/interactive.py` — simplification (~800 lignes supprimées)
- `src/loopforge/cli/textual_app/app.py` — adaptation
- `src/loopforge/cli/actions.py` — registre unifié
- `tests/test_command_parity.py` — nouveau
- `tests/test_action_registry.py` — nouveau

**Interface:**
```python
@dataclass
class AppCommandResult:
    command: str
    ok: bool
    target: ActionScope
    new_revision: int | None
    data: Any
    errors: list[AppCommandError]
    next_actions: list[ActionDescriptor]
    effects: list[str]

@dataclass
class AppCommandError:
    code: str
    message: str
    remediation: str
    recoverable: bool
```

**12 commandes à implémenter:**

| Commande | Module | Duplication actuelle |
|---|---|---|
| `InitProject` | `commands/init.py` | `cli/__init__`, `workflow.py`, `interactive.py` |
| `OpenProject` | `commands/open_project.py` | `cli/__init__`, `state_store.py` |
| `StartRun` | `commands/run.py` | `workflow.py`, `interactive.py` |
| `ResumeRun` | `commands/run.py` | `workflow.py`, `interactive.py` |
| `ApproveStage` | `commands/approve.py` | `workflow.py`, `interactive.py` |
| `ExecuteStage` | `commands/stage.py` | `workflow.py`, `interactive.py` |
| `VerifyRun` | `commands/verify.py` | `workflow.py`, `interactive.py`, shell |
| `ReviewRun` | `commands/review.py` | `workflow.py`, `interactive.py` |
| `ArchiveRun` | `commands/archive.py` | `workflow.py`, `interactive.py`, `app.py` |
| `Doctor` | `commands/doctor.py` | `cli/__init__`, `interactive.py` (2 implémentations !) |
| `LearnRun` | `commands/learn.py` | `workflow.py`, `interactive.py` |
| `ListRuns` | `commands/list_commands.py` | `cli/__init__` |

**Registre d'actions unifié:** garantir `available=true` → executeur + scope valide. Corriger les 6 actions fantômes de l'audit.

**Validation:**
- `tests/test_command_parity.py` — 12 scénarios, résultats identiques top-level/slash/TUI
- `tests/test_action_registry.py` — pas d'action `available=true` sans executeur
- Smoke: `version --json`, `/help` en shell

---

### Subtask 4 — Décomposition de la suite de tests (3-5 jours)

**Objective:** Séparer `tests/test_cli.py` (6022 lignes) en suites indépendantes. Builders via API publique. Couvre R21.

**Organisation cible:**

| Suite | Contenu | CI |
|---|---|---|
| `tests/unit/` | Modèles, resolvers, stockage, lifecycle, path resolvers, process runner | < 30s, obligatoire |
| `tests/integration/` | CLI via API publique, workflows, commandes applicatives | < 3min |
| `tests/tui/` | Textual headless, workers, snapshots | < 1min |
| `tests/fault/` | Pannes, corruption, concurrence, timeout | < 2min |
| `tests/e2e/` | Parcours complets sans modifier `run.json` | < 5min, optionnel |

**Files:**
- `tests/builders.py` — factories pour `ProjectConfig`, `RunState`, `ActionScope`
- Répertoires `tests/unit/`, `tests/integration/`, `tests/tui/`, `tests/fault/`, `tests/e2e/`

**Validation:** chaque suite exécutable indépendamment ; unit < 30s ; aucun test ne mute `run.json` directement.

---

### Subtask 5 — Rendu immuable et séparation des responsabilités (2-3 jours)

**Objective:** Aucun I/O (disque, Git, subprocess) dans le rendu TUI. Couvre R20.

**Files concerned:**
- `cli/textual_app/workers.py` — workers capturent identité, vérifient avant publication
- `cli/state_store.py` — snapshots immuables
- `cli/models.py` — `UiSnapshot` frozen
- `tests/test_rendering_isolation.py` — nouveau

**Règles:**
- Worker: capture `(project_id, run_id)` → lit → vérifie identité courante → publie ou jette
- `UiSnapshot`: `frozen=True`, pas de référence mutable
- Tout I/O avant construction du snapshot

**Validation:** `tests/test_rendering_isolation.py` — zéro `subprocess.run`/`open()` pendant rendu.

---

### Subtask 6 — Contrôles de dépendances et vérification (1-2 jours)

**Objective:** Garantir dépendances acycliques et façade stable. Couvre R19.

**Files concerned:**
- `tests/test_architecture.py` — nouveau
- `tests/test_engine_facade.py` — nouveau

**Tests:**
- Pas d'import `cli.*` depuis `engine.*`
- Pas d'import circulaire entre sous-modules engine
- Pas d'accès à `_private` depuis l'extérieur
- Tous les symboles publics `loopforge.engine` stables et réexportés

---

## Plan de test global

### Tests automatisés

| # | Test | Commande | Critère |
|---|---|---|---|
| T1 | Suite complète | `python -m unittest` | 0 échec, 0 erreur |
| T2 | Suite unitaire | `python -m unittest discover -s tests/unit` | < 30s, 100% vert |
| T3 | Parité surfaces | `python -m unittest tests.test_command_parity` | Mêmes résultats top-level/slash/TUI |
| T4 | Actions valides | `python -m unittest tests.test_action_registry` | `available=true` → executeur |
| T5 | Pas de cycles | `python -m unittest tests.test_architecture` | Dépendances acycliques |
| T6 | Façade stable | `python -m unittest tests.test_engine_facade` | Symboles publics préservés |
| T7 | Rendu sans I/O | `python -m unittest tests.test_rendering_isolation` | Pas de subprocess/open |
| T8 | Modèles typés | `python -m unittest tests.test_models` | Round-trip, rejet inconnus |
| T9 | Smoke CLI | `python -m loopforge version --json` | JSON valide |
| T10 | Smoke shell | `echo "/help" \| python -m loopforge shell --plain` | Pas d'erreur |
| T11 | Smoke runs | `python -m loopforge runs --json` | JSON valide |
| T12 | Whitespace | `git diff --check` | Propre |

### Tests manuels

| # | Scénario | Étapes |
|---|---|---|
| M1 | Parcours complet top-level | `init` → `run` → approve task → research → plan → approve → implement → verify → review → archive (tout en `--plain`) |
| M2 | Même parcours slash shell | `shell --plain`, `/run`, `/approve`, `/research`, `/plan`, etc. |
| M3 | Même parcours TUI | Actions disponibles identiques, pas d'action fantôme |
| M4 | Reprise après interruption | Ctrl+C pendant `verify`, relancer → reprise au bon stage |
| M5 | Mode machine JSON | `--json` sur chaque commande : premier octet stdout = `{` |
| M6 | Mode CSV | `--csv` sur `runs` : CSV valide sans préfixe humain |
| M7 | Changement projet TUI | Projet B → Projet A, données de A affichées |
| M8 | Archive TUI | Sélectionner run non-courant visuellement, archiver → bon run archivé |
| M9 | Mode `--plain` | Toutes commandes : pas d'ANSI, pas de spinner |
| M10 | Shell `--script` | `echo "/status --json" \| python -m loopforge shell --script` → JSON valide |

---

## Synthèse des livrables

| Livrable | PR estimés |
|---|---|
| Audit et baseline | 1 |
| 10 modèles typés + tests | 1 |
| 11 extractions de domaines + nettoyage final | 12 |
| 12 commandes applicatives | 2 |
| Adaptation CLI (top-level, slash, TUI) | 1 |
| Registre d'actions unifié | 1 |
| Décomposition des tests (5 suites + builders) | 2 |
| Rendu immuable | 1 |
| Contrôles d'architecture | 1 |
| **Total** | **22 PRs sur 4-5 semaines** |

---

## Scope Boundaries

**Included:**
- Extraction du monolithe `engine/__init__.py` en 11 domaines
- Couche de commandes applicatives unique
- Unification top-level/slash/TUI
- Décomposition de la suite de tests
- Modèles typés aux frontières
- Rendu TUI sans I/O
- Tests d'architecture

**NOT included:**
- Nouvelle fonctionnalité produit (wizards, packs, écrans)
- Orchestration distante ou marketplace
- Refonte cosmétique UI
- Modification des schémas persistants (Epic 2)
- Correction des bugs de sécurité (Epic 1)
- CI/CD et release (Epic 5)

---

## Dependencies and Assumptions

- **Epic 2 completed:** `ActionScope`, `EffectivePackContract`, `ProcessReceipt`, `RunState` et schémas persistants figés
- **Facades stables:** `loopforge.cli:main` et `loopforge.engine` restent compatibles
- **Imports Textual paresseux** préservés (`cli/interactive.py`, `cli/tui.py`)
- **Tests de caractérisation** écrits avant chaque extraction
- **Git requis** pour les runs mutables de la v1
- **Deux personnes** peuvent paralléliser Subtasks 4/5 avec Epic 4 après freeze des contrats au Subtask 3

---

## Risks and Mitigations

| Risque | Signal précoce | Mitigation |
|---|---|---|
| Big-bang refactor | Longue branche, tests insuffisants | Extraire un domaine à la fois, merge chaque PR verte |
| Correction de test au lieu du produit | Assertion modifiée sans contrat | Tests de caractérisation avant mouvement |
| Régression CLI silencieuse | Smoke test échoue après extraction | `version --json` après chaque PR |
| Import lazy Textual cassé | ImportError au démarrage headless | Test headless sans Textual en CI |
| Duplication résiduelle | Code similaire dans `interactive.py` et `workflow.py` | Revue : toute logique dupliquée → commande applicative |
| Cycle de dépendances | ImportError ou boucle | `test_architecture.py` en CI, bloque le merge |
| Perte de compatibilité façade | Symbole public manquant | `test_engine_facade.py` vérifie la liste blanche |