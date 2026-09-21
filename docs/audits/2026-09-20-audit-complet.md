# Audit LoopForge — 20 septembre 2026

État historique avant nettoyage. Voir le [suivi des corrections et des issues](2026-09-21-nettoyage-et-suivi.md)
pour les changements réalisés ensuite et leur validation.

## Verdict

Le workflow nominal local peut aller de la création de tâche au brouillon de publication, puis à la mémoire, aux métriques et à l'archivage. **Le projet ne peut toutefois pas être considéré comme fiable en l'état : plusieurs invariants de confiance, de concurrence et de validité des preuves sont contournables.** La suite de tests n'est pas verte.

L'audit relève **17 constats prioritaires : 8 P1 et 9 P2**. P1 signifie une correction prioritaire avant de s'appuyer sur les garanties du moteur ; P2 signifie une correction nécessaire pour la robustesse, les performances ou la validation du produit. Ces niveaux ne prétendent pas mesurer une exposition réseau : les reproductions sont locales.

Aucune correction du code produit n'a été effectuée. Le rapport porte sur le répertoire de travail existant, qui contenait déjà de très nombreuses modifications, et non seulement sur HEAD. Les projets, worktrees, commandes de test, paquets construits et journaux supplémentaires sont dans `/tmp/loopforge-audit-KNHUDy/`.

## Périmètre et méthode

- Lecture des règles du dépôt, de la carte des modules, des contrats sensibles, du catalogue de réutilisation et de `DESIGN.md`.
- Revue des chemins critiques : création et reprise de run, approbations, recherche/plan/revue, implémentation, vérification, brouillon local, stockage, verrous, index, packs, processus, CLI et rafraîchissement Textual.
- Deux exécutions complètes de `python -m unittest` ; reproductions ciblées des échecs et des anomalies absentes des tests existants.
- Parcours métier sur de vrais dépôts Git temporaires avec worktrees et adaptateur Python local, en utilisant les API publiques pour les transitions.
- Injection contrôlée d'échecs, altération d'un patch temporaire, tests de timeout et de confiance des checks locaux.
- Contrôles complémentaires de sélection entre deux runs, confirmation devenue obsolète, refus hors séquence, complétion d'une tâche et reprise avec identité incohérente.
- Mesure du nombre de lectures d'état à la sauvegarde ; construction et installation du wheel hors dépôt, sans téléchargement de dépendances.

Environnement : Linux, Python **3.14.7**, Textual **8.2.8**, Rich **15.0.0**, prompt_toolkit **3.0.53**. Le produit comporte 99 fichiers Python, soit environ 33 444 lignes dans `src/loopforge/` au moment de l'audit.

## Résultats des vérifications

| Vérification | Résultat |
| --- | --- |
| `python -m unittest`, passage 1 | 601 tests, 43,417 s ; **29 échecs, 4 erreurs, 1 ignoré** |
| `python -m unittest`, passage 2 | 601 tests, 43,565 s ; **30 échecs, 4 erreurs, 1 ignoré** |
| CLI structure/parité, packs effectifs, intégrité des résultats d'implémentation, tolérance aux pannes, migrations | **108 tests réussis** |
| Reproduction isolée des deux tests Textual d'annulation | **2 erreurs reproduites**, `NoMatches: #main-content` |
| ProcessRunner avec chemin Python résolu, uniquement dans le harnais de diagnostic | 13 tests ; 11 réussis, 1 échec, 1 ignoré |
| `python -m compileall -q src` | Réussi |
| `git diff --check` | Échec ; très nombreux CRLF signalés comme espaces finaux |
| Contrôle complémentaire avec `core.whitespace=cr-at-eol` | 10 lignes avec espaces finaux, dans des documents et `node_modules` ; aucun défaut restant dans `src`, `tests`, `pyproject.toml` |
| Construction du wheel avec `pip wheel --no-deps --no-build-isolation --no-index` | Réussie |
| Installation du wheel dans un répertoire temporaire, aide CLI, init/création/statut | Réussis ; import confirmé depuis le wheel installé |
| Lanceur Python `.agent/checks/diff_policy.py --help` | Réussi |
| Lanceur Bash `.agent/adapters/codex.sh`, sans arguments | Échec immédiat sur `set -euo pipefail`, dû aux CRLF |

L'écart entre les deux suites provient notamment d'un test concurrent supplémentaire en échec au second passage. Le test ignoré concerne la terminaison d'un arbre de processus Windows, indisponible sur Linux.

## Workflow vérifié étape par étape

| Étape | Observation |
| --- | --- |
| Initialisation | Config, identité projet et stockage extérieur créés correctement. |
| Création de tâche | `task_draft` créé ; tentative d'implémentation prématurée refusée. |
| Approbation initiale | Passage à `task_approved` réussi. |
| Recherche | Adaptateur local exécuté ; artefact accepté ; `research_ready`. |
| Plan | Artefact accepté ; `awaiting_approval` ; implémentation toujours refusée. |
| Approbation du plan | Passage à `implementation_ready` réussi. |
| Implémentation | Modification réelle du worktree temporaire ; candidat enregistré. |
| Vérification | Patch et contrôles exécutés ; revue et publication restent initialement non approuvées. Mais les gardes acceptent aussi une tentative échouée : LF-03. |
| Revue | Artefact produit ; **l'étape devient `task_draft` à la relecture** : LF-09. L'approbation reste possible grâce aux autres champs. |
| Approbation de revue | Autorise le brouillon local. |
| Préparation de publication | JSON local créé sans réseau ; refus avant revue confirmé. Validité du patch et des approbations insuffisamment contrôlée : LF-02 et LF-06. |
| Nouvelle tentative et récupération | Une tentative sur workspace sale échoue ; une tentative de récupération suivante réussit. Les anciennes validations survivent : LF-02. |
| Nouvelle vérification/revue | Le parcours redevient cohérent après exécution explicite de ces étapes. |
| Mémoire | Proposition acceptée ; aucune promotion automatique demandée par le harnais. |
| Métriques | Enregistrement et résumé réussis. |
| Archivage et reprise | Appels publics réussis ; cela ne valide pas une sémantique de désarchivage automatique. |
| Confirmation et sélection concurrente | **Approbation appliquée au mauvais run** si le run courant change : LF-14. |
| Complétion d'une tâche sans preuve initiale | `success_checks` complété mais `acceptance_criteria` reste vide : LF-16. |
| Reprise avec identité incohérente | Succès annoncé et sélection d'un autre run : LF-17. |

## Constats prioritaires

### LF-01 — P1 — Un remplacement local de checks contourne la confiance du pack

**Code :** [verification.py](../../src/loopforge/engine/verification.py), lignes 184–195 ; [packs.py](../../src/loopforge/engine/packs.py), `file_candidates`, `load_checks`, `freeze_pack_contract`.

Le moteur détermine si un pack est fourni par LoopForge à partir du chemin du `pack.json` figé. Or `load_checks` peut charger un `.loopforge/packs/generic-code/checks.json` local sans `pack.json` local. Le manifeste reste fourni par LoopForge, tandis que la commande provient du projet.

**Reproduction :** création d'un override contenant une commande qui écrit un simple fichier témoin. Après les étapes normales, `verify_run` réussit et le fichier est créé, alors que `is_trusted(hash)` vaut `False`. Le chemin enregistré pour le manifeste désigne bien le pack fourni par LoopForge.

**Impact :** une commande locale non approuvée est exécutée comme si elle provenait du pack fourni. Les checks reçoivent en outre l'environnement parent via `run_pack_check` ; la reproduction n'a lu aucun secret.

**Correction recommandée :** conserver la provenance effective des checks dans le contrat figé et appliquer la confiance à leur contenu et à leur origine, y compris pour les overrides partiels. Ajouter un test d'intégration sans manifeste local.

### LF-02 — P1 — Une nouvelle implémentation conserve les anciennes validations

**Code :** [execution.py](../../src/loopforge/engine/execution.py), `update_run_after_attempt`, lignes 1035–1075.

La mise à jour ajoute la tentative et change l'étape d'implémentation, mais conserve `verification`, le statut de revue approuvée, les gates et `publish_eligibility`.

**Reproduction :** implémentation ONE → vérification → revue → approbation → brouillon ; tentative refusée sur workspace sale ; récupération qui écrit TWO. Sans revérifier TWO, `prepare_draft_publication` retourne encore `ok=True`. Le workspace contient TWO, tandis que le patch retenu contient seulement ONE.

**Impact :** le moteur présente une nouvelle implémentation comme publiable avec des preuves et une approbation portant sur un état antérieur. Même l'échec intermédiaire laisse l'éligibilité à `True`.

**Correction recommandée :** invalider les étapes aval dès le début d'une tentative susceptible de modifier le workspace ; rattacher vérification, revue et approbation à une identité de candidat/patch. Conserver les anciens artefacts comme historique, sans autorité sur le nouveau candidat.

### LF-03 — P1 — Une implémentation échouée suffit à franchir la garde de vérification

**Code :** [verification.py](../../src/loopforge/engine/verification.py), lignes 124–127.

`has_candidate` vérifie seulement qu'une tentative quelconque possède un `returncode` non nul au sens de « différent de None ». Un code de sortie d'échec satisfait donc cette garde ; la réussite de la dernière tentative et la présence d'un candidat valide ne sont pas exigées.

**Reproduction :** l'adaptateur refuse une commande Python au nom non autorisé avant de modifier le workspace. La tentative est `failed`, l'implémentation `blocked`. Pourtant `verify_run` retourne `ok=True`, produit le hash du patch vide, puis la revue et le brouillon restent accessibles.

**Impact :** `verified` peut être annoncé sans implémentation de la tâche. Le scénario demandait un fichier qui n'existait pas. Les checks génériques passent mais ne prouvent pas ce critère métier.

**Observation associée :** `_build_criterion_results(['critical requirement'], [])` déclare ce critère `passed` avec zéro check, par `all([])`. Le rattachement implicite de tous les checks aux critères non associés peut également exagérer ce qui a été prouvé.

**Correction recommandée :** définir et valider le candidat admissible le plus récent, y compris les règles de récupération après un échec partiel. Distinguer un contrôle technique réussi d'un critère métier non évalué ; zéro preuve doit rester inconnu ou bloqué.

### LF-04 — P1 — Les verrous POSIX ne protègent pas les threads et ignorent le timeout

**Code :** [locking.py](../../src/loopforge/engine/locking.py), lignes 83–84 et `FileLock.acquire`.

La branche POSIX utilise `fcntl.lockf(fd, LOCK_EX)`, donc un verrou bloquant associé au processus. Des threads du même processus peuvent pénétrer simultanément dans la section critique. Un autre processus reste bloqué dans l'appel système avant que le délai Python puisse être contrôlé.

**Preuves :** tests existants d'exclusivité et de concurrence en échec ; au premier passage, compteur final 5 au lieu de 20 et 5 au lieu de 10. Reproduction interprocessus distincte : timeout demandé de 0,1 s, acquisition réussie après **1,216 s**, une fois le détenteur libéré.

**Impact :** perte de mises à jour et appels potentiellement bloqués au-delà du délai contractuel.

**Correction recommandée :** combiner exclusion entre threads et verrou interprocessus non bloquant avec deadline. Revoir aussi le retrait du fichier de verrou : supprimer son nom pendant que d'autres processus l'ont ouvert peut séparer les détenteurs sur des inodes différents.

### LF-05 — P1 — Un échec de verrou provoque une écriture sans verrou

**Code :** [engine/__init__.py](../../src/loopforge/engine/__init__.py), lignes 941–946 et `persist_project_config` ; [projects.py](../../src/loopforge/engine/projects.py), `save_registry`.

Les helpers interceptent toute exception des repositories et écrivent directement avec le stockage atomique. L'atomicité du remplacement de fichier ne remplace pas l'exclusion entre opérations.

**Reproduction par injection :** `RunRepository.write` lève `LockTimeoutError`. `persist_run_json` réussit néanmoins et la nouvelle donnée est présente sur disque.

**Impact :** une contention ou un conflit peut être transformé en écrasement silencieux. Par ailleurs, plusieurs opérations lisent l'état avant d'appeler `repo.write`, sans opération métier atomique ni comparaison de la révision lue ; verrouiller la seule écriture ne suffit pas.

**Correction recommandée :** propager les timeouts/conflits sous forme de résultat récupérable ; utiliser une transaction lecture–modification–écriture ou une comparaison de révision pour l'état autoritatif. Réserver les stratégies de reconstruction aux index dérivés.

### LF-06 — P1 — Le hash du patch n'est pas vérifié au moment du brouillon

**Code :** [stages.py](../../src/loopforge/engine/stages.py), lignes 173–180.

Le préparateur vérifie l'existence du patch et la présence d'une chaîne `sha256` dans l'état, sans recalculer l'empreinte du fichier.

**Reproduction :** ajout de quelques octets au patch après vérification et approbation. La préparation retourne `ok=True` et réutilise l'ancien SHA-256, différent du hash réel calculé par le harnais.

**Impact :** le brouillon peut désigner un artefact qui ne correspond plus à la preuve retenue. Il s'agit du brouillon local ; aucune publication distante n'a été effectuée.

**Correction recommandée :** confiner le chemin du patch, vérifier son hash et sa taille à l'utilisation, puis contrôler que l'approbation porte sur cette même empreinte.

### LF-07 — P1 — Un check expiré peut laisser son enfant continuer

**Code :** [adapter_runtime.py](../../src/loopforge/engine/adapter_runtime.py), `run_pack_check`, lignes 674–753 ; [verification.py](../../src/loopforge/engine/verification.py), boucle des checks.

Les checks passent par `subprocess.run` avec timeout, sans groupe supervisé ni transmission de l'événement d'annulation. L'annulation n'est consultée qu'entre les checks. `capture_output=True` accumule également toute la sortie avant de la réduire à 4 000 caractères.

**Reproduction :** un check lance un enfant, puis expire à une seconde. Son résultat est `timed_out`, mais l'enfant écrit un fichier après deux secondes. Ce processus de démonstration s'arrête ensuite de lui-même.

**Impact :** modifications possibles après que la vérification a annoncé son échec ; Ctrl-C peut attendre la fin du contrôle en cours ; consommation mémoire proportionnelle à toute la sortie.

**Correction recommandée :** utiliser le runner supervisé existant après correction de LF-08, avec capture bornée, annulation active et terminaison de l'arbre. Conserver explicitement le contrat d'environnement des checks.

### LF-08 — P2 — L'envoi du stdin échappe au délai du runner

**Code :** [process_runner.py](../../src/loopforge/engine/process_runner.py), lignes 131–146.

Le runner écrit et ferme entièrement stdin avant de commencer la collecte qui surveille le timeout et l'annulation. Un enfant qui ne lit pas peut bloquer cette écriture.

**Reproduction :** deux Mo d'entrée, enfant dormant 1,5 s, timeout demandé 0,15 s. L'appel revient après **1,516 s**. Il indique alors un timeout, mais le délai n'a pas borné l'exécution.

**Correction recommandée :** superviser simultanément l'écriture de stdin et la lecture des sorties ; commencer le contrôle du délai avant toute opération bloquante. Ajouter un cas où l'enfant ne consomme jamais son entrée.

### LF-09 — P2 — Une revue réussie est normalisée en brouillon de tâche

**Code :** [engine/__init__.py](../../src/loopforge/engine/__init__.py), constante `REVIEW_COMPLETE_STAGE` et lignes 301–304 ; [lifecycle.py](../../src/loopforge/engine/lifecycle.py), `RunStage` ; [workflow.py](../../src/loopforge/engine/workflow.py), lignes 155–165.

Le succès de revue écrit `review_complete`, absent de l'énumération `RunStage`. La normalisation traite cette valeur produite par le moteur comme inconnue et remplace `current_stage` par `task_draft`.

**Reproduction :** après la revue nominale, le résultat expose `review_complete`, puis `current_status` expose `task_draft`, tout en conservant `stage_statuses.review = complete`.

**Impact :** état persistant/présentation incohérents et consommateurs de `current_stage` trompés. L'approbation fonctionne encore dans le scénario parce qu'elle consulte d'autres champs.

**Correction recommandée :** unifier les constantes produites, les enums et la normalisation ; tester la relecture après chaque transition réelle.

### LF-10 — P2 — Un message Textual tardif déclenche une exception à la fermeture

**Code :** [textual_app/app.py](../../src/loopforge/cli/textual_app/app.py), lignes 320–323, 1384–1403.

Le handler de snapshot appelle `_sync_screen_surface`, qui cherche immédiatement les widgets. Pendant le démontage de l'écran, `screen_stack` peut encore exister alors que `#main-content` a disparu. La protection `NoMatches` située plus bas n'englobe pas cet appel.

**Preuves :** les deux tests d'annulation avant/après commit échouent lors de la sortie de `run_test`. Une exécution isolée reproduit les deux exceptions.

**Impact établi :** fermeture/annulation non propre de la console dans ces scénarios. Aucun élément ne permet d'attribuer à cette exception une perte de données ; ce point reste distinct de la concurrence du stockage.

**Correction recommandée :** cesser de traiter les publications pendant le démontage et garder les requêtes DOM dans une zone protégée. Attendre/annuler proprement les callbacks et workers concernés.

### LF-11 — P2 — Chaque sauvegarde reconstruit l'index entier

**Code :** [engine/__init__.py](../../src/loopforge/engine/__init__.py), lignes 937–948 ; [indexes.py](../../src/loopforge/engine/indexes.py), `read_run_index`, `update_run_index`.

`persist_run_json` marque l'index sale juste avant `update_run_index`. Celui-ci appelle `read_run_index`, qui refuse tout index marqué sale : la reconstruction complète est donc déclenchée même pour une sauvegarde ordinaire.

| Runs synthétiques ajoutés, en plus du run courant | Lectures de `run.json` pour une sauvegarde | Temps observé |
| --- | --- | --- |
| 10 | 12 | 3,56 ms |
| 100 | 102 | 8,88 ms |
| 500 | 502 | 31,75 ms |

Les mesures sont locales, sur fichiers temporaires et avec instrumentation ; elles ne prédisent pas la latence sur un disque utilisateur. Le nombre de lectures démontre néanmoins un coût O(N) à chaque mutation et une reconstruction systématique. La création successive de nombreux runs accumule ce coût.

**Correction recommandée :** lire l'index valide avant le marqueur transactionnel ou transmettre sa version déjà chargée à la mise à jour ; conserver la reconstruction pour la récupération. Protéger aussi la concurrence entre mises à jour et retrait du marqueur.

### LF-12 — P2 — Les lanceurs Bash de compatibilité sont inutilisables en CRLF

**Code :** [.agent/adapters/codex.sh](../../.agent/adapters/codex.sh), ligne 2, et autres lanceurs Bash au même format.

**Reproduction :** `bash .agent/adapters/codex.sh` échoue avant le traitement des arguments : `set: pipefail\r: invalid option name`.

**Impact :** rupture du chemin de compatibilité Linux, indépendamment de la disponibilité de Codex. Ce défaut ne démontre pas un échec du chemin normal utilisant les adaptateurs Python packagés.

**Correction recommandée :** imposer LF pour les scripts `.sh` via `.gitattributes`, normaliser ces seuls fichiers et tester leur entrée sans arguments. Éviter une renormalisation globale des nombreuses modifications utilisateur pendant cette correction.

### LF-13 — P2 — La suite mélange bugs produit et hypothèses de test non portables

**Code :** [test_process_runner.py](../../tests/test_process_runner.py), [test_terminal_execution.py](../../tests/test_terminal_execution.py), [test_action_registry.py](../../tests/test_action_registry.py), [test_cli.py](../../tests/test_cli.py), [test_terminal_capabilities.py](../../tests/test_terminal_capabilities.py).

Plusieurs échecs ne doivent pas être assimilés directement à des bugs produit :

- Les tests de ProcessRunner passent `sys.executable` comme symlink, explicitement refusé par la politique. En résolvant seulement ce chemin dans le harnais, neuf des dix échecs initiaux de ce module disparaissent. Le test POSIX restant construit un programme Python invalide (`if` composé après un point-virgule), ce qui ne teste pas la terminaison d'enfants.
- Des tests de terminal supposent les séparateurs Windows ou la présence de PowerShell tout en étant exécutés sur Linux ; une simulation d'`os.name` provoque aussi la création impossible d'un `WindowsPath` sous Linux.
- Le test Rich dépend des variables d'environnement de couleur/terminal sans les isoler.
- Le catalogue `KNOWN_ENGINE_ACTION_IDS` des tests manque sept actions effectivement produites par le moteur. Les qualifier de « phantom actions » est trompeur. Un autre test attend qu'une action inconnue soit disponible, alors que le produit la désactive.
- `tests/e2e/test_e2e_smoke.py` ne fait qu'un `assertTrue(True)` ; le test d'intégration nommé workflow ne couvre que init/création/liste. Les nombreux tests de `test_cli.py` apportent une couverture réelle, mais certains préparent leurs étapes en modifiant directement `run.json`, ce qui contourne des transitions comme LF-09.

**Correction recommandée :** rendre les tests indépendants de l'environnement et explicites sur les plateformes ; ne pas assouplir les règles d'isolation pour satisfaire une fixture. Ajouter un parcours réel continu avec relecture des états, puis des scénarios adverses LF-01 à LF-11. Les échecs de concurrence et de Textual, eux, sont des défauts reproduits.

### LF-14 — P1 — Une confirmation peut approuver un autre run que celui présenté

**Code :** [textual_app/app.py](../../src/loopforge/cli/textual_app/app.py), lignes 955–975 et `_execute_action` ; [interactive.py](../../src/loopforge/cli/interactive.py), `execute_guided_action` ; [workflow.py](../../src/loopforge/engine/workflow.py), `approve_plan`.

Le chargement du résumé vérifie la fraîcheur de l'identité avant son affichage, mais le callback de confirmation ne conserve que l'`ActionDescriptor`. Il ne fixe ni le run, ni sa révision, ni l'empreinte du plan présenté. L'exécution retrouve ensuite le run courant du projet.

**Reproduction :** deux runs A et B sont amenés à l'approbation du plan par les API publiques. Le vrai callback de `_show_confirmation` est préparé avec le résumé de A ; une seconde opération `resume_run(B)` simule une autre session CLI ; le callback reçoit ensuite l'accord. **Le gate de A reste `pending`, celui de B devient `approved`.** Le harnais intercepte seulement l'affichage de la modale et exécute synchroniquement le même handler de shell : il ne modifie pas les décisions d'approbation du moteur.

**Impact :** l'autorité humaine obtenue pour A est appliquée à B. Le verrouillage des seuls fichiers ne résout pas ce défaut de sélection, même sans écritures simultanées.

**Correction recommandée :** capturer un `ActionScope` immuable et la révision/empreinte de l'artefact lors de la demande ; les transmettre jusqu'à l'API d'approbation. Refuser une confirmation obsolète et afficher à nouveau la preuve du bon run. Tester un changement de run et une modification du plan pendant la modale.

### LF-15 — P2 — Une commande hors séquence détruit le statut déjà approuvé

**Code :** [stages.py](../../src/loopforge/engine/stages.py), lignes 360–368 ; [engine/__init__.py](../../src/loopforge/engine/__init__.py), `update_run_for_stage_blocker`.

Quand une étape demandée n'est pas la prochaine étape disponible, le moteur persiste son statut à `blocked` au lieu de retourner un refus sans transition de cette étape. Cette écriture a lieu avant toute exécution d'adaptateur.

**Reproduction :** plan approuvé, puis appel `execute_readonly_stage(stage='plan')`. Le retour est correctement négatif, mais `stage_statuses.plan` devient `blocked`, tandis que `human_gates.plan_approval.status` reste `approved`.

**Impact :** un appel répété ou mal ordonné rend le workflow incohérent et empêche l'implémentation jusque-là autorisée. Le moteur propose alors de refaire le plan.

**Correction recommandée :** distinguer le refus d'une commande d'un échec de l'étape effectivement en cours. Préserver l'état d'une étape terminée lors d'un refus hors séquence ; journaliser le refus séparément.

### LF-16 — P2 — La complétion d'une tâche ne synchronise pas les critères d'acceptation

**Code :** [workflow.py](../../src/loopforge/engine/workflow.py), lignes 510–512 ; [run_service.py](../../src/loopforge/engine/run_service.py), initialisation d'`acceptance_criteria` ; [verification.py](../../src/loopforge/engine/verification.py), construction de `criterion_results`.

La création initialise `acceptance_criteria` à partir des preuves demandées. Lorsque l'utilisateur crée une tâche incomplète puis la complète, `complete_task_definition` met à jour `success_checks` et `loop.md`, mais conserve l'ancien tableau `acceptance_criteria`.

**Reproduction :** création sans success check, puis complétion avec « New objective proof ». Résultat : `ok=True`, `success_checks=['New objective proof']`, **`acceptance_criteria=[]`**.

**Impact :** le chemin guidé produit un contrat différent du chemin où le même critère est fourni dès la création. Le rapport de vérification ne contient plus ce critère dans son tableau d'acceptation.

**Correction recommandée :** centraliser la mise à jour des champs qui représentent la preuve attendue et tester la parité création complète / création puis complétion, jusqu'au rapport de vérification.

### LF-17 — P2 — La reprise ne vérifie pas l'identité du run chargé

**Code :** [run_service.py](../../src/loopforge/engine/run_service.py), lignes 102–112. Comparaison utile : `archive_run` vérifie déjà l'égalité entre l'identifiant demandé et celui du fichier.

`resume_run(A)` charge le fichier sous le dossier A, puis copie son champ `run_id` dans `current_run_id` sans vérifier qu'il vaut A.

**Reproduction par injection de métadonnées incohérentes :** le fichier du run A contient l'identifiant d'un autre run C existant. `resume_run(A)` retourne `ok=True` avec `run_dir` pointant vers A ; l'appel suivant à `current_status` sélectionne pourtant C.

**Impact :** un fichier copié ou corrompu peut faire reprendre un autre travail que celui demandé, avec un résultat de reprise lui-même incohérent. Aucun scénario de corruption spontanée du fichier n'est affirmé ici : l'incohérence a été injectée volontairement.

**Correction recommandée :** vérifier l'identifiant et l'appartenance au projet avant de modifier la sélection ; retourner un diagnostic récupérable en cas de désaccord, sans modifier `current_run_id`.

## Points favorables et limites

Les gardes initiales de tâche et de plan, le refus de publication avant revue, l'isolation par worktree dans le parcours nominal, la compilation et le packaging fonctionnent dans l'environnement testé. Les 108 tests ciblés de contrats, migrations et résistance aux pannes passent. La préparation du brouillon est bien locale.

Les agents externes réels n'ont pas été invoqués : ni Codex, Claude Code, Kilo, Aider, OpenCode, mini-swe-agent, ni GitHub n'ont été utilisés pour réaliser une tâche ou publier. Leurs contrats de commande sont couverts par les tests disponibles, pas par une validation de chaque version installée. Windows, macOS, toutes les versions Python annoncées et un terminal humain réel restent hors validation native de cette session. Les tests Textual utilisent Pilot.

Le wheel a été testé avec les dépendances présentes sur cette machine ; aucune résolution de dépendances sur une machine vierge ni aucun audit de vulnérabilités de dépendances n'a été effectué. L'analyse de performance instrumente les lectures d'index ; elle ne constitue pas un profilage exhaustif CPU/mémoire de toutes les interfaces.

Un audit ne peut garantir l'absence de tout bug. Les constats ci-dessus suffisent en revanche à invalider l'affirmation que tout le workflow est actuellement sûr et cohérent.

## Ordre de correction proposé

1. **Confiance, cible des approbations et preuves :** LF-01, LF-02, LF-03, LF-06 et LF-14 ; tests adverses avant les changements.
2. **État concurrent :** LF-04 et LF-05 ; tests threads et processus réels, y compris timeout et conflit de révision.
3. **Processus bornés :** LF-07 et LF-08 ; annulation pendant un check, entrée bloquée, enfant survivant, sortie volumineuse.
4. **Cohérence, reprise et console :** LF-09, LF-10, LF-15, LF-16 et LF-17.
5. **Coût des sauvegardes et compatibilité :** LF-11 et LF-12.
6. **Validation fiable :** LF-13, puis deux suites complètes vertes et une matrice native Linux/Windows avec les versions Python supportées.

Les erreurs P1 devraient être traitées avant une optimisation structurelle générale ou une extraction supplémentaire du moteur : la priorité est de rendre les garanties existantes vraies et testables.

## Pièces de preuve locales

Répertoire : `/tmp/loopforge-audit-KNHUDy/`. Ces fichiers temporaires peuvent disparaître au nettoyage du système ; les résultats essentiels sont reproduits dans ce rapport.

| Fichier | Contenu |
| --- | --- |
| `unittest-1.log`, `unittest-2.log` | Deux suites complètes avec traces et noms exacts des tests en échec |
| `focused-contracts.log` | 108 tests ciblés réussis |
| `tui-repro.log` | Deux erreurs de fermeture reproduites isolément |
| `process-runner-resolved.log` | Diagnostic distinguant les fixtures Python des défauts de supervision |
| `workflow.jsonl`, `workflow.stderr` | Tentative refusée par l'adaptateur puis vérification et brouillon acceptés |
| `workflow-happy.jsonl`, `workflow-happy.stderr` | Parcours nominal, hash altéré, relecture de revue et injection de timeout de verrou |
| `recovery.jsonl`, `recovery.stderr` | Nouvelle implémentation sans invalidation, reprise, mémoire/métriques et processus survivant |
| `pack-index.jsonl` | Contournement de confiance et mesures de lectures d'index |
| `lock-timeout.json` | Timeout interprocessus non respecté |
| `selection.jsonl`, `selection.stderr`, `probe_selection.py` | Confirmation appliquée à un autre run, commande hors séquence, critères non synchronisés et reprise d'identité incohérente |
| `probe_workflow.py`, `probe_recovery.py`, `probe_pack_and_index.py`, `probe_lock.py` | Harnais de reproduction utilisés ; chemins de fixtures propres à cette session |
| `wheel-build.log`, `wheel-install.log`, `wheel-smoke.log`, `wheel-help.log` | Build et démarrage depuis le paquet installé |
| `compat-launcher.log`, `compat-python-help.log` | Diagnostic des lanceurs hérités |
| `diff-check.log`, `diff-check-ignore-cr.log` | Résultats du contrôle des espaces et des fins de ligne |
