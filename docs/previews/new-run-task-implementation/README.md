# New Run / Task — implémentation locale du design A

Design A retenu le 22 octobre 2026 : tâche et critères réunis.
L'instruction ultérieure « Fais l'implémentation » autorise ce travail produit.
Elle n'accorde aucune approbation à une tâche réelle du moteur.

## Comportement livré

- Page dédiée avec projet et chemin visibles, description multiligne, critères
  ajoutables/supprimables et grille subjective lorsque le validateur la demande.
- Projet, pack, profil et adapter chargés dans un worker. Valeurs secondaires
  à droite en grande largeur ; une colonne et pied fixe en petit terminal.
- Tab / Shift+Tab déplacent le focus ; Entrée reste une nouvelle ligne dans
  les éditeurs ; Ctrl+Enter envoie le formulaire. Le bouton natif reste
  accessible avec Tab puis Entrée. Les commandes globales ne capturent pas
  les lettres, flèches, slash, sélection ou copie dans les champs.
- Une seule opération en cours ; champs et commandes d'édition bloqués
  pendant l'enregistrement. Erreur : texte conservé ; changement de contexte
  ou issue incertaine : relecture du projet avant nouvel envoi.
- La création ouvre le run sur Task. Le résumé distingue les attentes de
  réussite des preuves consultables dans Evidences. Le Command Input et le
  dock d'action de Live sont conservés.
- Une tâche sans critères peut être créée, puis complétée avec « Save
  criterion » dans le même run. L'ajout n'est ni une vérification ni une
  approbation. L'approbation de Task utilise la confirmation et le périmètre
  existants ; elle ne lance pas Research.
- Une saisie modifiée ne se quitte qu'après décision, avec Keep editing
  focalisé par défaut. Un run déjà créé est conservé au retour à la liste.

Le formulaire partage une méthode d'intake typée avec `/run`. Aucune commande
shell n'est construite à partir du texte utilisateur. Filtres, autres dialogues
de saisie, CLI non interactive et façade restent sur leurs chemins existants.
La complétion reçoit un périmètre optionnel vérifié sous le verrou de projet ;
un ancien formulaire ne peut pas compléter un autre run devenu courant.

## Captures natives

Images issues du **rendu Textual des composants produit**, avec fixtures
synthétiques. Ce ne sont pas les dessins de la galerie de conception, ni une
preuve d'exécution d'un agent. La capture retire NO_COLOR seulement dans son
processus pour présenter la palette ; le produit conserve son comportement.

| Scène | Capture |
| --- | --- |
| A vide, 120 × 40 | [PNG](empty-120x40.png) · [SVG](empty-120x40.svg) |
| A rempli, 120 × 40 | [PNG](filled-120x40.png) · [SVG](filled-120x40.svg) |
| A rempli, 80 × 24 | [PNG](filled-80x24.png) · [SVG](filled-80x24.svg) |
| A rempli, 60 × 24 | [PNG](filled-60x24.png) · [SVG](filled-60x24.svg) |
| A rempli, 160 × 40 | [PNG](filled-160x40.png) · [SVG](filled-160x40.svg) |
| Grille subjective, champ focalisé | [PNG](rubric-120x40.png) · [SVG](rubric-120x40.svg) |
| Complétion d'une tâche, 80 × 24 | [PNG](complete-80x24.png) · [SVG](complete-80x24.svg) |
| Erreur récupérable | [PNG](error-80x24.png) · [SVG](error-80x24.svg) |
| Enregistrement en cours | [PNG](saving-80x24.png) · [SVG](saving-80x24.svg) |
| Sortie d'un brouillon modifié | [PNG](discard-80x24.png) · [SVG](discard-80x24.svg) |
| Task dans Live, approbation requise | [PNG](task-120x40.png) · [SVG](task-120x40.svg) |

Les références de polices distantes sont retirées des SVG. `layout.json`
conserve les dimensions et les rectangles des zones principales.

Démo native en lecture seule :

```sh
PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py
PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py --state empty
PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py --state rubric
PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py --state task
```

Les actions de cette fixture ouvrent une explication ; aucune création ni
approbation réelle n'est exécutée par la démo.

## Vérification et limites

Voir la [revue de code et inspection Impeccable](REVIEW.md) pour les contrôles,
les résultats complets et les trois erreurs préexistantes de la suite.

Un ancien run auquel manque une grille subjective ne peut pas être réparé par
l'ajout d'un critère : le formulaire explique cette limite et n'offre pas un
enregistrement impossible. Il ne propose aucune édition générale des tâches
déjà enregistrées. Les brouillons de saisie restent en mémoire dans la session,
sans sauvegarde après fermeture. Les dimensions inférieures à 60 × 24 et les
lecteurs d'écran n'ont pas reçu de recette native exhaustive.
