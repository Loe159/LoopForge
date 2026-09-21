# Nettoyage CLI/TUI et suivi de l’audit — 21 septembre 2026

Ce document complète [l’audit initial](2026-09-20-audit-complet.md), qui décrit
l’état avant correction. Les étapes ci-dessous distinguent les validations
locales de la préparation du commit demandé ensuite.

## Surfaces conservées

- `loopforge` et `loopforge shell` en terminal interactif ouvrent uniquement Textual.
- Les commandes CLI, JSON/CSV, `--plain`, `shell --command` et `shell --script` restent disponibles.
- L’invite Prompt Toolkit, son historique/autocomplétion, les menus du cockpit,
  le questionnaire de création et les réglages `keymap`/`statusline` sont supprimés.
- `loopforge run --task ...` crée une tâche sans approbation implicite. Sans
  nouvelle source, il affiche le run courant ; sans run ni source, il échoue avec une erreur d’usage.
- Les étapes utilisent le contrôleur partagé avec Textual :
  `loopforge shell --command "/do run-research --confirm --execution-mode headless"`.
  Les actions indisponibles restent refusées, même avec `--confirm`.
- Le mode d’exécution appartient aux actions `/do` et à `continue`, plus à `run`.

La façade publique `loopforge.cli:main`, les APIs du moteur et les lanceurs
`.agent` sont conservés. Aucune migration d’état ou fonctionnalité récente de
transcription n’a été supprimée. Les plans historiques restent des archives,
pas la documentation d’usage de l’interface supprimée.

## Corrections connexes

- Verrous POSIX non bloquants, deadline effective, descripteur par thread,
  fichiers de verrou persistants pour éviter la course d’inodes ; tests entre
  threads, entre processus et de réutilisation après libération.
- Reconnaissance de `review_complete` par la normalisation du moteur.
- Protection contre les snapshots reçus pendant le démontage de l’écran Textual.
- Ordre du transcript établi dès l’insertion des widgets, sans callback tardif
  après rafraîchissement ; conservation de l’identité des outils et du focus.
- Détection portable des chemins Windows du lanceur Kilo.
- Tests de processus avec interpréteur résolu, script POSIX de fork valide,
  environnement terminal contrôlé et PowerShell simulé dans les tests Windows.
- Tests des anciens menus migrés vers les commandes scriptables ; protections
  contre la réintroduction de `input()` et de Prompt Toolkit.
- Fins de ligne LF pour les sources et lanceurs, encadrées par `.gitattributes`.

Le guide Impeccable a cadré la vérification des rafraîchissements tardifs de la
TUI sans refonte visuelle. Son fichier dérivé `.impeccable/design.json` est
signalé obsolète par rapport à `DESIGN.md` ; aucune régénération hors périmètre.

## Issues GitHub

Une issue a été créée pour chaque constat. Elles restent ouvertes : une
correction locale n’est ni une livraison ni une validation Windows réelle.

| Constat | Issue | État du correctif local |
| --- | --- | --- |
| LF-01 — Un remplacement local de checks contourne la confiance du pack | [#32](https://github.com/Loe159/LoopForge/issues/32) | Non corrigé dans ce nettoyage |
| LF-02 — Une nouvelle implémentation conserve les anciennes validations | [#33](https://github.com/Loe159/LoopForge/issues/33) | Non corrigé dans ce nettoyage |
| LF-03 — Une implémentation échouée suffit à franchir la garde de vérification | [#34](https://github.com/Loe159/LoopForge/issues/34) | Non corrigé dans ce nettoyage |
| LF-04 — Les verrous POSIX ne protègent pas les threads et ignorent le timeout | [#35](https://github.com/Loe159/LoopForge/issues/35) | Correction et tests locaux |
| LF-05 — Un échec de verrou provoque une écriture sans verrou | [#36](https://github.com/Loe159/LoopForge/issues/36) | Non corrigé dans ce nettoyage |
| LF-06 — Le hash du patch n'est pas vérifié au moment du brouillon | [#37](https://github.com/Loe159/LoopForge/issues/37) | Non corrigé dans ce nettoyage |
| LF-07 — Un check expiré peut laisser son enfant continuer | [#38](https://github.com/Loe159/LoopForge/issues/38) | Non corrigé dans ce nettoyage |
| LF-08 — L'envoi du stdin échappe au délai du runner | [#39](https://github.com/Loe159/LoopForge/issues/39) | Non corrigé dans ce nettoyage |
| LF-09 — Une revue réussie est normalisée en brouillon de tâche | [#40](https://github.com/Loe159/LoopForge/issues/40) | Correction et tests locaux |
| LF-10 — Un message Textual tardif déclenche une exception à la fermeture | [#41](https://github.com/Loe159/LoopForge/issues/41) | Correction et tests locaux |
| LF-11 — Chaque sauvegarde reconstruit l'index entier | [#42](https://github.com/Loe159/LoopForge/issues/42) | Non corrigé dans ce nettoyage |
| LF-12 — Les lanceurs Bash de compatibilité sont inutilisables en CRLF | [#43](https://github.com/Loe159/LoopForge/issues/43) | Correction et tests locaux |
| LF-13 — La suite mélange bugs produit et hypothèses de test non portables | [#44](https://github.com/Loe159/LoopForge/issues/44) | Partiel : portabilité corrigée ; scénarios adverses et couverture E2E à compléter |
| LF-14 — Une confirmation peut approuver un autre run que celui présenté | [#45](https://github.com/Loe159/LoopForge/issues/45) | Non corrigé dans ce nettoyage |
| LF-15 — Une commande hors séquence détruit le statut déjà approuvé | [#46](https://github.com/Loe159/LoopForge/issues/46) | Non corrigé dans ce nettoyage |
| LF-16 — La complétion d'une tâche ne synchronise pas les critères d'acceptation | [#47](https://github.com/Loe159/LoopForge/issues/47) | Non corrigé dans ce nettoyage |
| LF-17 — La reprise ne vérifie pas l'identité du run chargé | [#48](https://github.com/Loe159/LoopForge/issues/48) | Non corrigé dans ce nettoyage |

Une suite verte ne couvre pas à elle seule les invariants restants de l’audit.
En particulier, confiance des checks, invalidation des approbations, identité du
run et intégrité du patch restent prioritaires ; ne pas présenter ce nettoyage
comme une résolution de ces risques.

## Éléments préexistants et récupération

Les modifications préexistantes ont été conservées. Quarante fichiers `.bak.*`
ont été sortis du dépôt vers `/tmp/loopforge-cleanup-26te7v/removed-backups/`.
Une archive initiale et un diff binaire avaient été créés dans le même dossier.
Ce dossier temporaire n’est plus accessible après les changements
d’environnement : la récupération de ces sauvegardes n’est pas garantie.
Le code actuel et le rapport restent présents dans le dépôt.

Les modifications préexistantes dans `.idea/`, `node_modules/` et `LICENSE` n’ont pas été
retouchées. Leur whitespace empêche actuellement `git diff --check` global
de réussir ; le contrôle du périmètre produit est propre.

## Validation

Validation finale sous Linux, Python 3.14.7 et Textual 8.2.8 :

- Deux exécutions consécutives de `python -m unittest`, sans modification du
  code entre elles : **607 tests, 0 échec, 0 erreur** en 47,110 s puis
  46,928 s. Un test de terminaison d’arbre de processus Windows est ignoré
  sur cette plateforme. Les chemins Windows simulés ne remplacent pas une
  validation sur Windows réel.
- Les 22 tests du transcript passent également isolément. La dernière
  correction supprime une course de rafraîchissement observée pendant une
  passe précédente ; le test vérifie désormais l’ordre avant tout délai UI.
- `python -m compileall -q src tests` : succès.
- Construction du wheel depuis une copie des sources hors du dépôt,
  installation dans un répertoire isolé sans dépendances téléchargées, puis
  import confirmé depuis cette installation : succès. `init --json`,
  `run --task ... --success-check ... --json`, `status --json` et
  `shell --command /status` réussissent dans un projet temporaire.
  Les dépendances déclarées ne contiennent plus Prompt Toolkit.
- `bash -n` sur tous les lanceurs `.agent/adapters/*.sh` : succès. Le lanceur
  Codex sans arguments affiche son usage et retourne le code attendu `1`,
  sans erreur de fins de ligne.
- `git diff --check -- src tests docs .agent pyproject.toml README.md
  CONTRIBUTING.md AGENTS.md .gitignore` : succès.
- `git diff --check` global : échec connu (code `2`) sur le whitespace
  préexistant de `.idea/`, `node_modules/sql.js/` et `LICENSE`, laissé intact.

Les journaux de cette validation sont dans
`/tmp/loopforge-validation-54YLIe/` (`final-1.log`, `final-2.log`,
`final-wheel.log`, `final-install.log`, `final-diff-all.log`) ; ce stockage
est temporaire. Les résultats ci-dessus constituent la synthèse durable.
Ce contrôle ne prétend pas valider des agents externes réels ni résoudre les
scénarios adverses encore suivis dans les issues.

## Deuxième passe : structure du dépôt

Après la demande explicite de nettoyer aussi les dossiers racine :

- 96 fichiers suivis retirés du working tree, après sauvegarde de leur contenu
  réel, modifications locales comprises.
- Suppression de `doc/` (doublon exact de `docs/agent/08-flows.md`), de
  `agent.md` (ancien contrat prototype), de `qa/` (spécifications sans runner),
  de `node_modules/` (SQL.js inutilisé) et de `.impeccable/` (métadonnées locales
  d’outillage ; `DESIGN.md` reste intact).
- Suppression des dossiers vides `.agents/`, `.codex/`, `legacy/`, `policies/`,
  `schemas/` et `$`.
- `.agent/` réduit à six shims Python de checks, un lanceur Python d’adapter et
  six lanceurs Bash. Cinq prototypes autonomes et les politiques, schémas,
  prompts et templates dupliqués ont été retirés. Les implémentations et
  contrats utilisés restent dans `src/loopforge/`.
- `artifacts/` déplacé intact hors du dépôt ; aucun résultat de campagne effacé.
- `.loopforge/` conservé : il contient notamment l’identité du projet et le
  pointeur vers le run courant. `.idea/` conservé, notamment ses changements
  en réserve ; `.venv/` et `.git/` conservés également.
- Règles Git ajoutées pour éviter de réintroduire les dépendances Node, états
  locaux et caches d’outillage. Elles ne retirent pas de l’index les fichiers
  IDE déjà suivis. La documentation courante distingue désormais le layout
  actif des plans historiques.

La sauvegarde durable de cette **deuxième passe** est
`/run/media/loe/Acer/Users/loedu/Documents/LoopForge-cleanup-20260921-ajItUT/`.
L’archive `before-structure-cleanup.tar` a été comparée aux fichiers d’origine
avant suppression (`tar -df`, succès). Le dossier contient aussi les anciens
`artifacts/`, la liste des 96 chemins retirés et les journaux de validation.
Elle ne remplace pas les anciennes sauvegardes `.bak.*` devenues inaccessibles
lors de la première passe.

Le plan de rangement courant est [documenté ici](../repository-layout.md).
Les quatre tests supplémentaires de `tests/test_repository_layout.py`
contrôlent la minceur des shims, le démarrage des lanceurs sans les anciennes
données, l’identité de l’implémentation de processus et l’absence des entrées
documentaires dupliquées.

Validation de cette deuxième passe :

- Tests ciblés : **73/73 réussis**.
- Deux passes complètes consécutives, sans modification du code entre elles :
  **611 tests, aucun échec ni erreur**, en 47,870 s et 47,681 s ; un test
  spécifique Windows ignoré sous Linux. Aucun test existant supprimé.
- Compilation Python et syntaxe des six lanceurs Bash : succès.
- `git diff --check` sur le périmètre produit et sa documentation : succès.
  Le contrôle global reste en échec sur les quatre fichiers `.idea/*.xml`
  préexistants et `LICENSE`, non modifiés par cette passe.
- Configuration `.loopforge/` comparée à la sauvegarde après nettoyage :
  identique (`tar -df`, succès).
- La racine passe de 21 à 10 dossiers, sans toucher aux sources produit.
  Les 96 suppressions représentent 5 982 lignes obsolètes ; les fichiers
  conservés de l’IDE restent suivis par Git, malgré la nouvelle règle ignore.

À ce stade, les modifications étaient locales, sans commit, push ou fermeture
d’issue.

## Préparation du commit sur master

Sur demande de l’utilisateur, `.impeccable/config.json` et
`.impeccable/design.json` ont été restaurés depuis la sauvegarde durable et
la règle d’exclusion `.impeccable/` a été retirée. Leur contenu est conservé,
sans régénération des métadonnées ; seules les fins de ligne sont normalisées.
La racine compte donc finalement 11 dossiers, et non 10.

Les quatre fichiers IDE `.idea/*.xml` précédemment suivis sont retirés de
l’index, mais restent intacts sur disque, avec les changements en réserve.
Une sauvegarde supplémentaire `ide-before-untracking.tar` est conservée à
côté de la sauvegarde structurelle. La licence racine est inchangée sur le
fond ; ses fins de ligne sont normalisées pour que le contrôle global passe.

Les données locales `.loopforge/`, `.venv/`, les caches et les sauvegardes
externes ne font pas partie du commit. Les 17 issues d’audit restent ouvertes :
publier le nettoyage ne résout pas les risques restants.

Dernière validation avant commit : **611 tests en 47,811 s, aucun échec ni
erreur, un test Windows ignoré**. Compilation Python, `git diff --check` et
`git diff --cached --check` réussis sur le périmètre complet. Les deux fichiers
Impeccable sont restaurés ; les états locaux ignorés sont exclus de l’index.
