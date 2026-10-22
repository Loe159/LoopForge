# Revue de code et inspection Impeccable — New Run / Task

Date : 22 octobre 2026. Périmètre : design A et suite Task.
Revue par l'auteur, sans certification indépendante ni approbation humaine du
workflow. Les prérequis AGENTS.md et les documents agent 01/03/04/05/06/07 ont
été relus ; DESIGN.md reste la référence des tokens et de la grille terminal.

## Revue du code

- Un seul chemin d'intake : `/run` et la page dédiée appellent
  `InteractiveShell.create_run_from_intake`, qui réutilise `create_run`.
  Les chaînes contenant guillemets, retours à la ligne, slash, `--`, Unicode,
  dollar ou backticks restent des données. Aucun interpréteur shell ajouté.
- Le chargement et l'enregistrement quittent la boucle de rendu. Le
  formulaire reçoit des valeurs de contexte ; l'App utilise le contrôleur
  d'opération existant et publie les snapshots habituels.
- La sélection de projet, le run courant et les révisions sont revérifiés
  avant envoi. La complétion utilise en plus le périmètre moteur optionnel,
  contrôlé sous le verrou du projet. Les anciennes commandes sans périmètre
  gardent leur signature compatible et leur comportement.
- Les champs sont gelés pendant une opération ; une activation répétée ne
  crée pas un deuxième run. Un refus connu permet un nouvel essai. Une
  exception, dont l'issue peut être incertaine, demande une relecture du
  contexte avant un nouvel envoi.
- Aucun champ de lifecycle n'est modifié par la CLI. La complétion et
  l'approbation sont distinctes ; la confirmation conserve le contrôle du
  projet, du run, de la révision et de l'artefact. Research reste une autre
  action, même après approbation explicite de Task.
- Les valeurs de Task sont du texte littéral, jamais du Rich markup. La
  grille vient du contrat chargé par le moteur. Les résultats de vérification
  ne sont pas inférés de la présence de critères.
- `TextEntryScreen` reste inchangé pour les filtres et commandes. Les styles
  de la page et des confirmations Task sont limités à leur surface ; les
  fichiers TCSS sont inclus par la règle de packaging existante.

Un défaut trouvé pendant les premiers tests a été corrigé : une publication
de fin de complétion pouvait être associée à l'ancienne action « complete-task ».
Le contexte de lecture est désormais vidé avant l'ouverture du résultat,
et le snapshot frais publie « approve-task ». Le test existant qui vérifie
cette transition continue de s'appliquer au nouveau formulaire.

## Inspection visuelle et UX

Skill Impeccable appliqué avec les règles Operate, harden et craft floor, dans
l'identité établie. Inspection du formulaire et des états aux dimensions
60 × 24, 80 × 24, 120 × 40 et 160 × 40. Le détecteur web n'a pas été utilisé
comme preuve de qualité pour des composants Python/Textual.

Contrôlés : hiérarchie tâche/critères/action, focus visible, labels permanents,
contrastes issus de DESIGN.md, statut désactivé, récupération d'erreur,
préservation du texte, page défilable avec pied fixe, grille subjective,
dialogue de sortie, résumé Task et maintien de Command Input dans Live.

Corrections groupées après inspection : suppression de l'apparence active du
bouton désactivé, couleurs des barres de défilement, association du bouton
Remove à son champ, réduction du pied en grande hauteur pour garder Add
criterion visible, compte de critères et guidance de focus en petit terminal.
Le rendu conserve la mesure du formulaire à 160 colonnes.

Les premières captures de démo ont été écartées : le contexte synthétique
était appliqué avant la fin du montage du composant. La fixture attend
désormais le montage ; les captures finales montrent les valeurs chargées,
et la capture de grille place le focus dans le champ concerné. Le parcours
produit réel a été exercé séparément par le test d'intégration.

## Tests et portée des preuves

- `tests/test_task_composer.py` : **15 tests**, clavier et texte multiligne,
  plusieurs critères, suppression et focus, grille conditionnelle, sortie de
  brouillon, tailles, double envoi, refus, réessai, changement de contexte,
  saisie gelée, limite d'un ancien run sans grille, intake typée/slash,
  complétion périmétrée et parcours réel Home → création → approbation.
- Passage ciblé initial : **142 tests réussis** dans les nouveaux tests, les
  tests Textual existants, les frontières CLI, les services moteur et la
  composition Live. Le test réel de route ajouté ensuite réussit aussi.
- Vérification des 11 SVG/PNG et des rectangles de mise en page : réussie.
- `compileall` et `git diff --check` : réussis.

Deux passages complets consécutifs sur les sources finales inchangées :

| Passage | Tests | Durée | Échecs d'assertion | Erreurs | Ignorés |
| --- | --- | --- | --- | --- | --- |
| 1 | 782 | 265.569 s | 0 | 3 préexistantes | 3 préexistants |
| 2 | 782 | 272.992 s | 0 | 3 préexistantes | 3 préexistants |

Commande : `PYTHONPATH=src .venv/bin/python -m unittest`. Journaux :
`/tmp/loopforge-task-full-final-1.log` et
`/tmp/loopforge-task-full-final-2.log`.
[checks.json](checks.json) conserve les résultats et les empreintes des
sources. Aucun nouveau test n'est ignoré. Le passage préliminaire
avait les mêmes trois erreurs ; il ne remplace pas ces deux passages finaux.

Les erreurs connues sont les sous-cas `empty stdout`, `invalid Markdown` et
`partial headings` de
`CliTests.test_readonly_research_retains_invalid_candidates_and_allows_retry`.
Le test relit un ancien chemin de candidat rejeté après son archivage et reçoit
`FileNotFoundError`. La revue Live précédente les a reproduites sur un export
propre de HEAD, avant ces refontes. Le code d'archivage n'est pas modifié ici.
La suite complète reste donc en échec pour cette cause ; aucune réussite
globale n'est déduite des seuls tests ciblés.

Les tests qui créent ou approuvent un run utilisent des répertoires temporaires.
Ils ne valent pas approbation d'une tâche réelle du projet. La recette ne
couvre pas tous les émulateurs de terminal ni les lecteurs d'écran, et ne
constitue pas une certification d'accessibilité. Les captures synthétiques
ne prouvent pas une exécution réelle de harness.
