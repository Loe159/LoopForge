# Parcours par écran Textual

## Home

Entrée : `loopforge` dans un TTY.

Actions à tester :

1. vérifier le titre, la liste des projets et les runs récents ;
2. `j`/`k` et flèches changent la sélection sans modifier le produit ;
3. `Enter` ouvre le projet sélectionné ;
4. `n` ouvre la modal de création de run ;
5. `Ctrl+P` revient à Home depuis chaque écran ;
6. `Ctrl+K` ouvre les actions disponibles ;
7. `Ctrl+C` quitte lorsqu'aucune opération n'est active.

## Project

Chemin : Home → sélectionner un projet → `Enter`.

Actions :

1. vérifier nom, branche et nombre de runs ;
2. sélectionner un run et `Enter` ;
3. `/` filtre la liste puis restaure la liste avec une valeur vide ;
4. `n` crée un nouveau run ;
5. `a` affiche une confirmation d'archive ;
6. `Esc` revient à Home.

## Run

Chemin : Project → sélectionner un run → `Enter`.

Actions :

1. vérifier tâche, état global, acteur, pipeline, blockers et prochaine action ;
2. `Enter` exécute ou confirme uniquement l'action éligible ;
3. `e` ouvre Evidence ;
4. `s` ouvre Settings ;
5. `Ctrl+K` ne propose que les actions valides ;
6. `Esc` revient à Project ;
7. pendant une opération, `Ctrl+C` annule sans quitter l'application.

## Evidence

Chemin : Run → `e`.

Actions :

1. liste les artefacts présents sans lire tous leurs contenus en boucle ;
2. `Enter` ouvre un preview borné ;
3. `/` recherche un terme ;
4. `c` copie seulement après ouverture d'un élément ;
5. `x` exporte vers `artifacts/exports/` ;
6. premier `Esc` ferme le preview, second `Esc` revient au Run.

## Settings

Chemin : Run → `s`.

Vérifier : thème, statusline, keymap, adapter, projet, branche et révision du snapshot. `Esc` revient au Run.

## Modals

Pour chaque modal TextEntry, Confirmation et RecoverableError :

- le titre et la conséquence sont compréhensibles ;
- `Esc` annule sans effet ;
- une saisie vide ne déclenche rien ;
- une validation unique ne s'exécute pas deux fois ;
- le focus revient à l'écran précédent ;
- une erreur n'arrête pas tout le TUI si elle est récupérable.
