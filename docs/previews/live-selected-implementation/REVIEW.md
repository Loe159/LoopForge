# Live — inspection Impeccable et revue de code

Inspection du 21 octobre 2026, après l'implémentation de la composition validée.
Revue effectuée par le même agent ; aucune revue indépendante n'est revendiquée.

## Défaut trouvé et corrigé

**P1 — Entrée sur un bouton de lecture pouvait déclencher l'étape suivante.**
Reproduction avec une action Ready disponible : focus sur `run-view-context`,
Entrée, puis un appel à `request_action` au lieu du changement de vue.

La garde de `LoopForgeApp.check_action` laisse désormais Entrée au bouton
`run-*` focalisé, sur la surface principale. Elle ne s'applique pas aux modales
ni aux écrans Settings. À l'ouverture d'un run, le focus automatique est retiré
du premier bouton après le changement de surface : l'Entrée générale conserve
son comportement initial, puis Tab permet de choisir un contrôle précis.
Les actualisations ordinaires ne retirent pas le focus.

Le test `test_enter_on_run_controls_never_dispatches_next_stage` couvre
Context, Raw et le maintien de Ctrl+Enter. Les tests existants d'approbation
initiale, de complétion de tâche et de sélection d'adapter passent également.
Localisation : `src/loopforge/cli/textual_app/app.py`, méthodes `check_action`,
`_open_home_run` et `action_open_selected`.

## Inspection de l'interface

Les critères Impeccable sont appliqués à une interface de terminal : hiérarchie,
palette de `DESIGN.md`, contrôle clavier, états et dimensions. Ce n'est pas une
certification WCAG ni une exécution du protocole web dans un navigateur.

- Captures réelles Textual examinées : Live Ready 120 × 40, Context et Evidences
  120 × 36, Live Ready 60 × 24 et Approval 80 × 24. Fixtures synthétiques ;
  aucune exécution d'agent réelle n'est déduite des captures.
- Composition respectée : reçu sans boutons, navigateur et document, titres en
  capitales, orange pour l'approbation, commande persistante et prochaine action.
- À 60 × 24 et 80 × 24, le flux est réduit à quatre lignes défilables ; le
  bandeau et la commande restent accessibles. C'est une limite de densité
  visible, pas un affichage simultané de tout le reçu.
- Ratios calculés depuis la palette : texte secondaire / fond 10,87:1 ; texte
  atténué / fond 5,87:1 ; orange / surface de commande 10,06:1 ; sélection
  lavande / texte inverse 11,61:1. Le terminal réel et `NO_COLOR` peuvent
  modifier le rendu ; aucune validation de lecteur d'écran n'est revendiquée.

Commande exécutée : `impeccable detect --json src/loopforge/cli/textual_app`.
Résultat `[]`, code de sortie 0 ; conservé dans
`/tmp/loopforge-live-impeccable-audit.json`. La couverture documentée du
détecteur concerne principalement HTML/CSS/JSX/TSX : ce résultat ne prouve
pas l'absence de défaut dans Python ou Textual CSS. La preuve utile ici reste
la lecture du code, les captures Textual et les pilotes d'interaction.

## Revue de code et limites

- Les actions Ready et Approval réutilisent les descripteurs, le dispatch et
  les confirmations existants. Aucun champ du cycle moteur n'est modifié par
  le rendu. Les états occupé, actualisation, action indisponible et modale sont
  traités avant le raccourci de l'action suivante.
- Context et Evidences partagent un lecteur. Les clés de sélection incluent
  run/stage/session/vue ; les mises à jour du même périmètre gardent les widgets.
  Raw reste littéral et les chemins d'artefacts sont confinés sans symlinks.
- La fin de session seule n'est pas une réussite. Les compteurs reposent sur
  des snapshots complets ; les reçus de vérification sont associés au candidat
  et séparés de la sortie déclarée par l'agent.
- Les aperçus sont bornés et chargés hors des callbacks de rendu. Aucun
  benchmark de très gros runs ni essai sur tous les émulateurs de terminal
  n'a été réalisé.

Aucun autre défaut P0/P1 n'a été identifié dans ce périmètre après correction.
Cela ne garantit pas tous les scénarios d'exécution possibles.

## Vérification

- Tests ciblés de cette revue : **13 réussis** ; journal
  `/tmp/loopforge-live-review-focused.log`.
- Compilation de `src` et `git diff --check` : réussis.
- Deux passages complets consécutifs demandés par `docs/agent/06-build-test-run.md` :
  **767 tests chacun, trois erreurs préexistantes, trois tests ignorés**, aucun
  échec d'assertion. Commande : `PYTHONPATH=src .venv/bin/python -m unittest`.
  Journaux `/tmp/loopforge-live-review-full-1.log` (244,681 s) et
  `/tmp/loopforge-live-review-full-2.log` (241,606 s). Les trois erreurs portent
  exactement sur les mêmes sous-cas CLI de conservation après réessai ; aucun
  autre échec n'apparaît dans ces deux passages. La suite reste en échec à cause
  de ces erreurs et ne satisfait donc pas l'exigence « zéro erreur » du dépôt.

Les trois erreurs CLI préexistantes et leur reproduction dans un export propre
de HEAD sont décrites dans le [rapport d'implémentation](README.md).
