# Flux fonctionnels

## Résumé

LoopForge est un moteur de workflow agentique CLI-first en Python, sans serveur HTTP ni base de données. Toutes les données métier sont stockées dans des fichiers JSON locaux (configuration projet `.loopforge/config.json`, état de run `run.json`, artefacts de workflow). Le module est autonome — il ne consomme ni ne fournit de contrats à d'autres modules du workspace Proginov. Il interagit avec GitHub (`gh` CLI) pour lire des issues et optionnellement signaler des bugs. Les flux fonctionnels sont centrés sur les états de workflow (intake, recherche, planification, implémentation, vérification, revue, publication) qui transforment des artefacts fichier.

## Flux entrants

### In-GitHubIssues — Issues GitHub comme tâches d'entrée

- **Donnée :** `GitHubIssueRef` (owner, repo, number, url), contenu d'issue (number, title, body, labels) — utilisé comme définition de tâche pour initialiser un run
- **Projet source :** GitHub (API via `gh` CLI, dépôt du projet utilisateur)
- **Composant source :** `gh issue view` / `gh issue list` (appels subprocess)
- **Composant d'entrée :** `GitHubIssueClient.view()`, `GitHubIssueClient.list_open()` (`src/loopforge/cli/github.py:99-168`)
- **Déclenchement :** Commande CLI `loopforge intake` avec URL d'issue ou ID numérique
- **Fréquence :** À la demande (manuel)
- **Contrat :** GitHub CLI (`gh`) en ligne de commande, parsing JSON stdout — aucune API HTTP directe
- **Sens des données :** Entrant (lecture seule)
- **Statut :** confirmé
- **Evidence :**
  - Consommateur : `tools/LoopForge/src/loopforge/cli/github.py:99-130` — `view()` appelle `gh issue view --json number,title,body,url,labels`
  - Modèle : `tools/LoopForge/src/loopforge/cli/models.py` — `GitHubIssueRef`, `IssueReadResult`
  - Intake : `tools/LoopForge/src/loopforge/cli/intake.py` — utilise `GitHubIssueClient.resolve()`
  - Architecture : `docs/agent/02-architecture.md:66-69`

### In-PackDefinitions — Packs de workflow (bundled + projet)

- **Donnée :** `pack.json` (métadonnées : skills, agents, permissions, workflow stages, checks, protected paths, memory rules), résolu en `EffectivePackContract`
- **Projet source :** Fichiers locaux — `src/loopforge/packs/<name>/` (bundled) ou `<project>/.loopforge/packs/<name>/` (local override)
- **Composant source :** Système de fichiers local
- **Composant d'entrée :** `PackRegistry` (`src/loopforge/engine/packs.py:53-70`) — résolution d'héritage, validation, hydratation
- **Déclenchement :** Commande `loopforge init` (sélection du pack) ou `loopforge run` (résolution du pack effectif)
- **Fréquence :** À l'initialisation de projet et création de run
- **Contrat :** Schéma `pack.json` + fichiers de skills/agents/permissions/workflow — résolus par `PackRegistry.load_contract()`
- **Sens des données :** Entrant (lecture seule de configuration)
- **Statut :** confirmé
- **Evidence :**
  - Moteur : `tools/LoopForge/src/loopforge/engine/packs.py:53-70` — `PackRegistry.__init__()`, `load_contract()`
  - Modèle : `tools/LoopForge/src/loopforge/engine/packs.py:23-50` — `EffectivePackContract` dataclass
  - Architecture : `docs/agent/02-architecture.md:53-58`

## Flux sortants

### Out-RunState — État de workflow persistant (fichiers JSON/Markdown)

- **Donnée :** `config.json` (projet : project_id, profile, run_root), `run.json` (workflow state : current_stage, stage_statuses, human_gates), artefacts natifs (`task.md`, `research.md`, `plan.md`, `progress.md`, `verification.md`, `review.md`, `memory.md`, `exchange.json`)
- **Projet destination :** Système de fichiers local — `.loopforge/config.json` dans le projet, `run.json` et artefacts dans `LOOPFORGE_HOME`
- **Composant source :** `engine/__init__.py` (APIs `create_run()`, `execute_readonly_stage()`, `verify_run()`, etc.)
- **Composant de sortie :** `JsonStore.write_object()` (`src/loopforge/engine/storage.py:22-45`) — écriture atomique JSON
- **Déclenchement :** Transitions de workflow (commandes `loopforge run`, `loopforge continue`, `loopforge verify`, `loopforge review`)
- **Fréquence :** À chaque étape du workflow
- **Contrat :** Schémas `CURRENT_RUN_SCHEMA`, `CURRENT_CONFIG_SCHEMA` (`src/loopforge/engine/models/schema.py`), `NATIVE_RUN_FILES`
- **Sens des données :** Sortant (écriture sur disque)
- **Statut :** confirmé
- **Evidence :**
  - Moteur : `tools/LoopForge/src/loopforge/engine/__init__.py:158-170` — `NATIVE_RUN_FILES` (run.json, task.md, research.md, plan.md, etc.)
  - Storage : `tools/LoopForge/src/loopforge/engine/storage.py:22-45` — `write_object()` atomique
  - Schémas : `tools/LoopForge/src/loopforge/engine/models/schema.py`
  - Architecture : `docs/agent/02-architecture.md:31-50`

### Out-GitHubBugReport — Signalement de bugs LoopForge

- **Donnée :** Rapport de bug formaté (kind, title, description, expected, actual, screen) avec redaction de chemins et secrets
- **Projet destination :** Dépôt GitHub `Loe159/LoopForge` (issues)
- **Composant source :** `GitHubIssueClient.build_project_report()` (`src/loopforge/cli/github.py:170-210`)
- **Composant de sortie :** Formatage de rapport pour ouverture manuelle d'issue (pas d'API `gh issue create` automatique)
- **Déclenchement :** Commande `loopforge report` (bug, feature, optimization)
- **Fréquence :** Manuel (rare)
- **Contrat :** Template d'issue GitHub standard
- **Sens des données :** Sortant (rapport utilisateur, pas de données projet)
- **Statut :** confirmé
- **Evidence :**
  - CLI : `tools/LoopForge/src/loopforge/cli/github.py:170-210` — `build_project_report()` avec redaction
  - Dépôt cible : `tools/LoopForge/src/loopforge/cli/github.py:13` — `LOOPFORGE_GITHUB_REPOSITORY = "Loe159/LoopForge"`

## Flux internes structurants

### Internal-WorkflowStageMachine — Machine d'état du workflow

Le flux central de LoopForge est la machine d'état en 7 étapes : `task → research → plan → implementation → verification → review → publication`. Chaque transition est normalisée par `normalize_run_workflow_state()` (`engine/__init__.py`) et persiste dans `run.json`. Les étapes readonly (`research`, `plan`, `review`) valident des sections obligatoires et bloquent les mutations. Les étapes mutatives (`implementation`, `verification`) invoquent des agents externes (Codex, Claude Code, Kilo, Aider, OpenCode) via l'adapter `loopforge.adapters`.

- **Donnée :** `run.json` (current_stage, stage_statuses, human_gates, publish_eligibility), artefacts par étape (research.md, plan.md, etc.)
- **Composants :** `engine/__init__.py` (lifecycle APIs), `engine/lifecycle.py` (state machine), `cli/workflow.py` (handlers)
- **Déclenchement :** Commandes CLI `run`, `continue`, `verify`, `review`, `approve`, `prepare`
- **Evidence :**
  - Lifecycle : `tools/LoopForge/src/loopforge/engine/lifecycle.py` — `DEFAULT_STATE_MACHINE`, `RunStage`, `StageStatus`
  - Normalisation : `tools/LoopForge/src/loopforge/engine/__init__.py` — `normalize_run_workflow_state()`
  - Architecture : `docs/agent/02-architecture.md:31-50`

### Internal-AgentExecution — Exécution d'agents externes via adapters

Les étapes `implementation` et `verification` invoquent des agents LLM externes (codex, claude-code, kilo-code, aider, opencode, mini-swe-agent) via l'adapter local. L'adapter exécute les commandes dans un workspace isolé (git worktree ou shared checkout), capture les résultats, et les valide via `validate_implementation_result()`.

- **Donnée :** Commandes shell agent + arguments, résultats d'exécution (stdout, fichiers modifiés)
- **Composants :** `engine/__init__.py` → `loopforge/adapters/kilo_code.py` (et autres adapters) → processus agent externe
- **Déclenchement :** `continue_run()` après approbation du plan
- **Evidence :**
  - Adapters : `tools/LoopForge/src/loopforge/adapters/kilo_code.py` — `kilo_command_with_prompt()`, `headless_run_command()`
  - Validation : `tools/LoopForge/src/loopforge/checks/` — `validate_implementation_result()`
  - Engine : `tools/LoopForge/src/loopforge/engine/__init__.py:87-95` — `SUPPORTED_ADAPTERS`

### Internal-ProjectRegistry — Registre de projets

Le `ProjectRegistry` (`engine/projects.py`) maintient un registre JSON (`LOOPFORGE_HOME/projects/registry.json`) de tous les projets connus avec leur `project_id`, chemin canonique, et dernière attention. Les projets sont indexés par ID (pas par nom) pour supporter les déplacements et clones.

- **Donnée :** `registry.json` (project_id, canonical_path, last_attention, schema_version)
- **Composants :** `engine/projects.py` — `register_project()`, `list_registered_projects()`, migration de racines legacy
- **Déclenchement :** `loopforge init`, `loopforge open`, `loopforge projects`, TUI home screen
- **Evidence :** `tools/LoopForge/src/loopforge/engine/projects.py:21-50` — `PROJECTS_DIRECTORY`, `REGISTRY_FILE`, `ProjectRegistration`

## Flux potentiels ou obsolètes

*Aucun flux potentiel ou obsolète identifié. Le module est autonome et ses flux sont tous vérifiés.*

## Travaux planifiés

*Aucun travail planifié documenté.*