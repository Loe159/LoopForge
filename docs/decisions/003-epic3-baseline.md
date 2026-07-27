---
title: "Epic 3 — Architectural extraction: baseline audit"
type: decision-record
date: 2026-07-27
topic: epic3-architectural-extraction
parent_roadmap: 2026-07-22-001-refactor-loopforge-product-hardening-plan
github_issue: https://github.com/Loe159/LoopForge/issues/29
artifact_contract: decision-record/v1
artifact_readiness: final
---

# Epic 3 — Baseline Audit

Snapshot de l'état du code avant le début des extractions du monolithe.
Produit par la Subtask 0 du plan d'implémentation Epic 3.

---

## 1. Baseline de tests

**Commande d'exécution :**
```
python -m unittest discover -s tests -p "test_*.py"
```

> **Note :** `python -m unittest` sans `discover` ne trouve aucun test car
> `tests/__init__.py` est vide et aucun protocole `load_tests` n'est défini.
> La commande canonique documentée dans `docs/agent/06-build-test-run.md` reste
> `python -m unittest`, mais le repo exige actuellement le mode `discover`.

**Résultat de référence (master, avant Epic 3) :**

| Métrique | Valeur |
|---|---|
| Tests exécutés | **429** |
| Succès | **407** |
| Échecs (failures) | **18** |
| Erreurs (errors) | **0** |
| Ignorés (skipped) | **4** |
| Durée | **204 s** |

### 1.1 — Échecs préexistants (18)

Les 18 échecs partagent une **cause racine unique** : la machine à états du
workflow rejette des transitions attendues. Le symptôme dominant est :

```
No transition from 'task_draft' for event 'verification_request'
```

| # | Test | Symptôme |
|---|---|---|
| 1 | `test_cli.CliTests.test_continue_recovers_from_failed_deterministic_verification` | `verification_pending` != `verification_blocked` |
| 2 | `test_cli.CliTests.test_guidance_reports_draft_ready_blocked_verify_failed_and_verified_states` | `verification_pending` != `verification_blocked` |
| 3 | `test_cli.CliTests.test_incomplete_task_cannot_be_approved_or_researched` | `True is not false` |
| 4 | `test_cli.CliTests.test_pack_protected_paths_contribute_risk_rules` | `1 != 0` |
| 5 | `test_cli.CliTests.test_run_cockpit_after_review_prepares_draft_pr_publication` | `1 != 0` |
| 6 | `test_cli.CliTests.test_run_cockpit_approves_plan_for_implementation` | `plan_approved` != `implementation_ready` |
| 7 | `test_cli.CliTests.test_run_cockpit_approves_verified_work_for_review` | `1 != 0` |
| 8 | `test_cli.CliTests.test_run_cockpit_approves_verified_work_for_review` | `task_draft` != `review_ready` |
| 9 | `test_cli.CliTests.test_run_issue_id_uses_inferred_github_remote_when_configured` | `task_draft` != `task_approved` |
| 10 | `test_cli.CliTests.test_run_no_input_after_review_does_not_prepare_draft_publication` | `1 != 0` |
| 11 | `test_cli.CliTests.test_run_no_input_does_not_approve_review_after_verification` | `1 != 0` |
| 12 | `test_cli.CliTests.test_run_without_task_prompts_when_interactive` | `task_draft` != `task_approved` |
| 13 | `test_cli.CliTests.test_shell_verify_runs_pack_checks` | `1 != 0` |
| 14 | `test_cli.CliTests.test_strict_profile_requires_confirm_for_verify_and_memory_promotion` | `1 != 0` |
| 15 | `test_cli.CliTests.test_verify_blocked_for_untrusted_local_pack` | `not trusted` absent du message |
| 16 | `test_cli.CliTests.test_verify_generates_patch_policy_risk_and_pack_checks` | `1 != 0` |
| 17 | `test_cli_textual_app.TextualFoundationTests.test_pilot_approves_initial_task_after_confirmation` | `pending` != `approved` |
| 18 | `test_implementation_result_integrity.ImplementationResultIntegrityTests.test_public_continue_fixture_uses_protocol_wrapper` | `1 != 0` |

**Interprétation :** ~13 des 18 échecs pointent vers une régression de la
machine à états du workflow (`engine/lifecycle.py`). Les runs restent bloqués à
`task_draft` ou `plan_approved` au lieu d'avancer vers `implementation_ready` ou
`review_ready`. Ce n'est **pas** causé par Epic 3 — c'est l'état de `master`.

**Engagement pour Epic 3 :** les extractions doivent préserver exactement ces
18 échecs (ni plus, ni moins) jusqu'à ce qu'ils soient corrigés séparément. La
métrique de non-régression est : 429 tests, 18 failures, 0 errors.

### 1.2 — Tests ignorés (4)

Tous sont des gardes plateforme-spécifiques (Windows) :

| Test | Raison |
|---|---|
| `test_concurrency.TestFileLock.test_lock_pid_file_contains_current_pid` | PID non écrit sur Windows |
| `test_concurrency.TestFileLock.test_lock_timeout` | LK_NBLCK immédiat sur Windows |
| `test_process_runner.TimeoutTests.test_timeout_kills_process_tree_tree_posix` | Termination de process group POSIX-only |
| `test_fault_tolerance.TestFileLockStaleDetection.test_stale_pid_lock_is_detected_and_removed` | Verrous obligatoires Windows |

### 1.3 — Smoke tests

| Test | Résultat | Note |
|---|---|---|
| `python -m compileall -q src` | **OK** | Aucune erreur de syntaxe |
| `git diff --check` | **OK** | Pas d'erreur whitespace |
| `python -m loopforge version --json` | **Échec d'invocation** | Le package n'a pas de `__main__.py`. Le payload JSON lui-même est valide via `loopforge.cli:main(['version','--json'])`. **Action suggérée :** ajouter `src/loopforge/__main__.py` ou corriger le plan de test T9 pour utiliser `loopforge.cli:main`. |

### 1.4 — Modules de test (18 fichiers)

| Module | Domaine | Réfs `run.json` |
|---|---|---|
| `test_cli.py` | CLI end-to-end, lifecycle complet | **68** |
| `test_cli_evidence.py` | Commandes evidence/reporting | 0 |
| `test_cli_presentation.py` | Formatage de sortie | 0 |
| `test_cli_structure.py` | Façade CLI, handlers, modèles | 0 |
| `test_cli_textual_app.py` | Application TUI Textual | 0 |
| `test_cli_tui.py` | Contrats TUI | 0 |
| `test_cli_ux_contracts.py` | Contrats UX | 0 |
| `test_concurrency.py` | Opérations concurrentes | 3 |
| `test_effective_pack.py` | Résolution effective pack | 0 |
| `test_engine_services.py` | JsonStore, PackRegistry, Metrics | 4 |
| `test_fault_tolerance.py` | Corruption, pannes | 5 |
| `test_implementation_result_integrity.py` | Résultats d'adapter | 2 |
| `test_lifecycle.py` | Stages du lifecycle | 0 |
| `test_migration.py` | Logique de migration | 0 |
| `test_migration_v0_1_0.py` | Migration v0.1.0 | 5 |
| `test_path_resolvers.py` | Résolution de chemins | 0 |
| `test_process_runner.py` | Process runner | 0 |

**87 références directes à `run.json`** dans les tests. Le plan (Subtask 4)
demande qu'aucun test ne mute `run.json` directement après décomposition.

---

## 2. Cartographie du monolithe `engine/__init__.py`

**Taille : 8 913 lignes.** La structure observée correspond au tableau du plan
d'implémentation (lignes 50-62). Voici la cartographie par domaine :

### 2.1 — En-tête, constantes, imports (lignes 1-210)

- Imports depuis 13 sous-modules déjà extraits (`lifecycle`, `packs`, `metrics`,
  `storage`, `projects`, `indexes`, `models.schema`, `models.migrations`,
  `git_state`, `path_resolvers`, `doctor`, `adapters.kilo_code`, `checks`)
- Constantes workflow : stages, statuts, profils, adapters, clés config
- `WORKFLOW_STAGES`, `READONLY_WORKFLOW_STAGES`, `REQUIRED_LOOP_SECTIONS`, etc.

### 2.2 — Templates intégrés (lignes 384-483)

- `TEMPLATES` : `templates/loop.md`, `templates/memory.md`,
  `templates/scratch.md`, `templates/exchange.json`

### 2.3 — Dataclasses de résultats (lignes 486-710)

17 dataclasses `frozen=True` définissant l'API publique de l'engine :

`InitResult`, `RunResult`, `StatusResult`, `ContinueResult`, `StageResult`,
`VerifyResult`, `LearnResult`, `MetricsRecordResult`, `MetricsSummaryResult`,
`DashboardResult`, `RunListResult`, `ProjectListResult`, `IndexRepairResult`,
`GlobalRunListResult`, `OpenProjectResult`, `ResumeRunResult`,
`CompactContextResult`, `ConfigUpdateResult`, `InstallationResult`,
`GuidedAction`, `GuidanceResult`, `ActionScope`

> **Note pour Subtask 1 :** `ActionScope` (ligne 711) est déjà un dataclass
> complet avec `validate()` et `revalidate()`. C'est le modèle le plus abouti
> et peut servir de gabarit.

### 2.4 — Sections par domaine cible

| Domaine cible | Lignes actuelles | Fonctions clés observées |
|---|---|---|
| **installation** | 1504-1810 | `install_loopforge()`, `repository_root()`, gestion pip/git/subprocess |
| **project_service** | 2075-2439 | `new_config()`, `normalize_config()`, `initialize_project()`, `open_project()`, `update_project_config()`, `set_default_adapter()`, `archive_run()`, `archive_current_run()` |
| **workflow** | 1152-1411, 8708-8913 | `initial_workflow_state()`, `validate_task_definition()`, `normalize_run_workflow_state()`, `apply_*_approval()`, `implementation_gate_blockers()`, `continue_run()` |
| **memory** | 1414-1497, 2832-3339 | `ensure_templates()`, `ensure_project_memory()`, `durable_memory_items()`, `render_run_memory_snapshot()`, `learn_run()` |
| **artifacts** | 1831-1979 | `native_artifact_state()`, `parse_frontmatter()`, `markdown_sections()`, `loop_contract_state()` |
| **run_service** | 5042-5558 | `resume_run()`, `create_run()`, `new_run_id()`, `_rollback_run_creation()` |
| **execution** | 5567-6140, 7131-7707 | `execute_attempt()`, `update_run_after_attempt()`, metrics helpers |
| **stages** | 6665-7127 | `execute_readonly_stage()`, `next_readonly_stage()`, `prepare_draft_publication()` |
| **verification** | 7752-8250 | `verify_run()`, pack checks, patch generation |
| **status_service** | 3342-4179, 8708-8913 | `describe_next_step()`, `current_status()`, `current_guidance()`, `workflow_stage_guidance()`, `dashboard_snapshot()` |
| **workspace** | 2441-2659 | `detect_git_base_commit()`, `git_toplevel()`, `prepare_run_workspace()`, `run_workspace_path()`, `codex_workspace_preflight_blockers()` |

### 2.5 — Fonctions utilitaires partagées (lignes 772-1150)

Ces fonctions sont utilisées transversalement et devront soit rester dans la
façade, soit être placées dans un module `engine/_internal.py` :

`utc_now()`, `project_config_dir()`, `project_config_path()`, `loopforge_home()`,
`platform_data_home()`, `platform_cache_home()`, `default_run_root()`,
`read_json()`, `write_json_atomic()`, `persist_run_json()`,
`persist_project_config()`, `_sync_project_indexes()`, `index_diagnostics()`,
`run_doctor()`, `rebuild_indexes()`

### 2.6 — Plus grandes fonctions encore dans le monolithe

| Fonction | Lignes approx. | Domaine |
|---|---|---|
| `create_run()` | 5286-5558 (~270 lignes) | run_service |
| `continue_run()` | 8724-8913 (~190 lignes) | workflow |
| `verify_run()` | 7752-8250 (~500 lignes) | verification |
| `execute_attempt()` | 5567-6140 (~570 lignes) | execution |
| `execute_readonly_stage()` | 6665-7127 (~460 lignes) | stages |
| `current_status()` | 3398-3477 (~80 lignes) | status_service |
| `workflow_stage_guidance()` | 3499-3650 (~150 lignes) | status_service |
| `learn_run()` | 2832-3339 (~510 lignes) | memory |

---

## 3. Cartographie des dépendances CLI → engine

### 3.1 — Fichiers CLI important de `loopforge.engine` (7)

| Fichier | Rôle | Conforme ? |
|---|---|---|
| `cli/__init__.py` | **Façade** — réexporte 35 symboles publics | Oui (rôle de façade) |
| `cli/app.py` | Handlers top-level via `context.api` | **Oui** |
| `cli/workflow.py` | Handlers workflow via `context.api` | **Oui** |
| `cli/interactive.py` | Shell slash — appels engine directs | **Non** (28 symboles, bypass) |
| `cli/textual_app/app.py` | TUI — appels engine directs | **Non** (3 symboles, bypass) |
| `cli/state_store.py` | Loaders directs | **Non** (4 symboles) |
| `cli/actions.py`, `presentation.py`, `ui.py`, `parser.py` | DTOs/constantes seulement | Oui |

### 3.2 — Accès problématiques confirmés

| Fichier | Ligne | Accès | Statut |
|---|---|---|---|
| `cli/interactive.py` | 2125 | `from loopforge.engine import _pack_registry` | **Privé — à corriger** |
| `cli/textual_app/app.py` | 208 | `from loopforge.engine import resume_run` | **Bypass handler** |
| `cli/state_store.py` | 67 | `from loopforge.engine import current_status` | **Bypass handler** |

### 3.3 — Candidats au remplacement par commandes applicatives (16)

| Commande slash / TUI | Symbole engine | Ligne |
|---|---|---|
| `/init` | `initialize_project()` | interactive.py:979 |
| `/run`, `/fork` | `create_run()` | interactive.py:1044, 1963 |
| `/continue` | `continue_run()` | interactive.py:1143 |
| `/verify` | `verify_run()` | interactive.py:1208 |
| `/learn` | `learn_run()` | interactive.py:1260 |
| `/doctor` | `DoctorService()` | interactive.py:2081 |
| `/adapter`, `/config` | `set_default_adapter()` | interactive.py:954, 1591 |
| `/trust`, `/untrust` | `_pack_registry()`, `pack_trust_store()` | interactive.py:2125, 2145 |
| `/update` | `install_loopforge()` | interactive.py:2206 |
| `/resume` | `resume_run()` | interactive.py:1434 |
| `/archive` | `archive_current_run()` | interactive.py:2063 |
| `/approve` | `approve_plan()`, `approve_review()`, `approve_initial_task()` | interactive.py:598, 619 |
| `/complete-task` | `complete_task_definition()` | interactive.py:619 |
| `/compact` | `compact_current_context()` | interactive.py:1342 |
| TUI adapter picker | `set_default_adapter()` | textual_app/app.py:304 |
| TUI run open | `resume_run()` | textual_app/app.py:211 |

### 3.4 — Doublons de comportement (top-level vs slash vs TUI)

7 opérations ont **à la fois** un handler conforme (`cli/app.py`/`cli/workflow.py`)
**et** un appel direct dans `cli/interactive.py` :

`init`, `run`, `continue`, `verify`, `learn`, `doctor`, `update`

C'est la duplication cœur que la Subtask 3 (commandes applicatives) doit
éliminer.

---

## 4. Sous-modules déjà extraits (aucune duplication détectée)

Les 13 sous-modules suivants ont été vérifiés : `__init__.py` les importe mais
ne redéfinit pas leur contenu.

`engine/lifecycle.py`, `engine/packs.py`, `engine/metrics.py`,
`engine/storage.py`, `engine/projects.py`, `engine/indexes.py`,
`engine/models/schema.py`, `engine/models/migrations.py`,
`engine/git_state.py`, `engine/path_resolvers.py`, `engine/doctor.py`,
`engine/repositories.py`, `engine/locking.py`, `engine/recovery.py`,
`engine/process_runner.py`

---

## 5. Risques identifiés pour l'exécution

| Risque | Mitigation |
|---|---|
| 18 échecs préexistants masquent les régressions | Métrique de non-régression stricte : 429/18/0 avant et après chaque PR |
| `python -m loopforge` cassé (pas de `__main__.py`) | Le smoke test T9 du plan échouera ; créer `__main__.py` en Subtask 0 ou corriger le test |
| 87 références directes à `run.json` dans les tests | Subtask 4 : remplacer par builders via API publique |
| `create_run()` et `verify_run()` font 270-500 lignes | Extraire en gardant la signature publique intacte ; tests de caractérisation obligatoires |
| `interactive.py` a 28 bypass engine | Subtask 3 : chaque slash command doit router via commande applicative |

---

## 6. Décisions de la Subtask 0

### D0.1 — Métrique de non-régression

**Décision :** Chaque PR d'extraction doit préserver exactement **429 tests,
18 failures, 0 errors, 4 skipped**. Aucune correction des 18 échecs
préexistants ne sera tentée pendant Epic 3.

**Rationale :** Les échecs sont une régression de `engine/lifecycle.py` non
causée par Epic 3. Les corriger nécessite une investigation séparée.

### D0.2 — Smoke test `version --json`

**Décision :** Créer `src/loopforge/__main__.py` qui délègue à
`loopforge.cli:main`. Cela répare `python -m loopforge version --json` sans
changer la façade.

**Rationale :** Le plan de test T9 et plusieurs smoke tests reposent sur cette
invocation. Le correctif est trivial et non-intrusif.

### D0.3 — Ordre d'extraction

**Décision :** Suivre l'ordre du plan (2.1 → 2.12), en partant des domaines
les moins couplés (installation, artifacts) vers les plus couplés (workflow,
execution, verification).

**Rationale :** Les domaines à faible couplage valident le processus
d'extraction avec un risque minimal. Les domaines à fort couplage bénéficient
des patrons établis.
