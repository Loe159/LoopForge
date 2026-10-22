# New Run / Task — design A retenu

Conception : 21 octobre 2026. Retour reçu : 22 octobre 2026.
Statut : **design A implémenté et contrôlé localement ; trois erreurs préexistantes dans la suite complète**.
Autorisation d'implémentation reçue le 22 octobre 2026 : « Fais
l'implémentation. » Cette instruction autorise le travail produit et ses tests,
sans accorder d'approbation à une tâche réelle du moteur.

Le retour utilisateur retient **A — tâche et critères réunis**, sans ajustement
sur le projet, la description, les critères, la navigation, les états ou Task.
Aucune remarque générale n'est ajoutée. Il précise : « Ce retour ne déclenche
aucune implémentation ni approbation moteur. » La variante B est conservée
ci-dessous comme proposition comparée, sans être retenue pour l'implémentation.
L'ordre d'implémentation reçu ensuite remplace la restriction du retour de
design pour le travail de code ; la frontière d'approbation moteur reste intacte.

La [livraison locale et ses captures natives](../previews/new-run-task-implementation/README.md)
et la [revue de code / inspection Impeccable](../previews/new-run-task-implementation/REVIEW.md)
documentent désormais le résultat. Les sections de conception ci-dessous
conservent le brief validé.

## Brief

- **Usage : Operate.** Un développeur vient d'un projet sélectionné et veut
  préparer une tâche locale dont la réussite sera reconnaissable. Il doit
  identifier le projet, écrire sa tâche, préciser ses critères, créer le run,
  puis relire et approuver sa tâche explicitement.
- **Identité :** [DESIGN.md](../../DESIGN.md), terminal Textual, monospace hérité,
  grille en cellules, cadres carrés, surfaces violet graphite, focus lavande,
  attention orange. La refonte de Live récemment réalisée reste la référence
  d'intégration. Les mentions historiques « non implémenté » de PRODUCT/DESIGN
  sont signalées ici sans réécrire ces documents hors périmètre.
- **Deux compositions demandées :** A, tâche et critères réunis ; B, description
  puis critères. La réponse « fais les 2 design et je verai » fixe ce choix
  d'exploration ; aucun troisième concept ni choix automatique n'est imposé.
- **Livrable :** [galerie locale](../previews/new-run-task-review/index.html),
  19 maquettes statiques PNG/SVG/texte, capture native du composant actuel,
  formulaire de retour groupé et critères de recette. La galerie fonctionne
  sans réseau, serveur, dépendance distante ni écriture d'un workflow.

## État actuel et vérité produit

`LoopForgeApp.action_new_run` ouvre `TextEntryScreen`, dialogue générique à un
seul `Input`. Le callback passe le texte à `InteractiveShell.cmd_run`. La
complétion d'une tâche existante ouvre un deuxième dialogue à une ligne avec
le libellé « Save proof ».

Le moteur permet déjà de créer un run avec `task`, plusieurs `success_checks`
et une `subjective_rubric`. Le slash `/run --task ... --success-check ...`
utilise ces mêmes paramètres. Une tâche non vide peut être créée sans
critère, mais `validate_task_definition` exige un critère avant approbation.
En profil `autonomous`, une tâche que le moteur classe subjective exige
aussi une grille d'évaluation.

La complétion publique `complete_task_definition(success_check=...)` ajoute
**un** critère à un run incomplet ; elle n'est pas une API d'édition générale
de tâche, de suppression de critères ou de modification de grille. Les
maquettes ne proposent pas ces opérations sur un run enregistré. La grille
conditionnelle est donc recueillie **avant** création. La réparation d'un
ancien run auquel manque uniquement une grille reste une limite du produit,
à expliquer avec le blocage moteur, sans suggérer un enregistrement impossible.

Les critères restent des attentes écrites ; leur enregistrement ne constitue
pas un résultat de vérification. Créer, compléter, approuver et exécuter
Research restent des opérations distinctes.

## A — Tâche et critères réunis

Une page dédiée remplace la petite modale. Le projet et son chemin restent
visibles au-dessus du formulaire. Le champ Task multiligne précède les champs
Success criterion, chacun avec un label permanent. Add criterion et Remove
modifient seulement le brouillon en mémoire avant création.

En grande largeur, une colonne secondaire rappelle les valeurs du projet et
la suite du parcours. Elle ne contient ni paramètres fictifs ni nouvelles
permissions. Le formulaire conserve une mesure utile, même à 160 colonnes.
Le pied fixe porte une seule action primaire « Create run » et Back.

Le bouton est indisponible sans tâche ; une explication reste visible.
L'absence de critères laisse la création possible avec une indication claire
de la complétion attendue dans Task. A favorise la relecture de l'ensemble ;
son compromis est le défilement plus long en terminal bas.

## B — Description puis critères

Une même surface possède deux étapes locales :

1. **Task :** grand éditeur multiligne ; « Continue » passe aux critères et
   **ne crée pas de run**.
2. **Criteria :** résumé de la tâche, critères éditables, « Back to task »
   sans perte de saisie, et « Create run » comme action finale.

Les numéros 1/2 et 2/2 indiquent un avancement réel de saisie, pas le workflow
moteur. Aucun wizard supplémentaire de confirmation avant création.
Créer sans critère reste possible à la seconde étape, avec son effet annoncé.
B réduit la quantité de contenu à traiter à la fois ; son compromis est une
transition supplémentaire pour une tâche courte.

## Suite commune — Task

Après succès confirmé de création, ouvrir le run qui vient d'être créé et
présenter sa tâche dans la vue Live à l'étape Task. Il ne s'agit pas d'ajouter
un cinquième onglet à Live / Context / Changes / Evidences.

Si le moteur demande une complétion, présenter la tâche enregistrée en lecture
et un champ de critère, avec « Save criterion ». Appeler l'opération existante,
garder le même run, actualiser son contrat et sa prochaine action. Une erreur
garde la saisie ; une complétion acceptée ne donne aucune approbation.

Si l'approbation est disponible, afficher « Approval required » en orange et
l'action moteur dans le dock existant. Ouvrir la confirmation existante via
`request_action` : projet, run, révision et résumé frais doivent correspondre.
Le bouton s'appelle « Approve task » ; Back/Esc reviennent sans décision.
L'approbation de tâche ne lance pas automatiquement Research. Le Command Input
actuel du run est conservé. Quitter un run déjà créé ne supprime pas ce run.

## Règles d'interaction

| Situation | Comportement proposé |
| --- | --- |
| Entrée dans New Run | Projet individuel requis ; nom et chemin visibles, focus dans Task. Aucun sélecteur « All projects » admissible. |
| Saisie | Entrée ajoute une ligne ; collage de texte ou de `/commande` reste du texte. Aucune commande depuis les champs de tâche/critère. |
| Navigation | Tab / Shift+Tab suivent l'ordre visuel ; déplacement du curseur natif dans les éditeurs ; aucun raccourci global ne capture la saisie. |
| Action primaire | Activation du bouton natif avec Tab puis Entrée toujours possible. Ctrl+Enter est une accélération proposée, soumise aux limites des terminaux. |
| Focus | Cadre et curseur visibles ; retour B vers A de saisie restaure champ et position ; aucune prise de focus par actualisation de fond. |
| Nouvelle ligne dans un critère | Un critère est un champ, pas une ligne : des retours à la ligne ne créent pas implicitement de nouveaux critères. |
| Critère vide | Omettre les champs entièrement blancs à l'envoi ; ne pas ajouter de minimum de longueur ou de limite arbitraire. |
| Critère supprimé du brouillon | Focus au critère voisin ou à Add criterion ; pas de saut à Create run. |
| Quitter sans modification | Retour immédiat à la sélection précédente. |
| Quitter une saisie modifiée | Confirmation justifiée par perte de texte, Keep editing par défaut ; Esc garde la saisie. Rien n'est sauvegardé après fermeture de l'application. |
| Création en cours | Une seule opération ; bouton indisponible et libellé Creating ; texte conservé ; aucun indicateur de pourcentage inventé. |
| Échec récupérable | Message moteur fidèle, récupération concrète et saisie conservée ; pas de notification éphémère comme seule explication. |
| État de création incertain | Rafraîchir le résultat/current run via les APIs avant d'offrir Retry ; ne pas créer un deuxième run à l'aveugle. |
| Projet/configuration modifié | Garder le brouillon et suspendre la création ; refaire la vérification du contexte. Pas de transfert silencieux à un autre projet. |
| Run courant déjà présent | Prévenir près de Create run que le nouveau run deviendra courant ; conserver et rendre retrouvable l'ancien run. |
| Validation | Réutiliser `validate_task_definition` ; explication neutre avant interaction, erreur près du champ après tentative/édition invalidée. Aucun succès métier déduit de la saisie. |

## Dimensions, lecture et accessibilité

- 120 × 40 : champs et contexte côte à côte ; ordre de lecture Task puis
  critères puis action, sans métriques qui concurrencent la saisie.
- 160 × 40 : mesure du formulaire conservée, espace secondaire calme ; pas
  d'étirement de l'éditeur sur toute la largeur.
- 80 × 24 et 60 × 24 : une colonne, contexte réduit à une ligne, contenu
  défilable, pied d'action conservé. Une mention indique les critères sous
  le pli ; le déplacement de focus fait défiler le champ entier.
- Si le terminal est encore plus petit, privilégier la zone d'édition et un
  moyen de revenir ; ne pas promettre la même composition qu'à 60 × 24.
- Contrastes de la palette contrôlés pour labels, aide et placeholders ;
  couleur complétée par texte, cadre et focus. Aucun état communiqué par
  couleur seule. Pas de défilement horizontal imposé à la saisie normale.
- Conserver Unicode et retours à la ligne à l'enregistrement ; convertir
  seulement les marqueurs de chrome en mode ASCII. Ne pas transformer le
  contenu utilisateur en Rich markup, en commande ou en Markdown exécutant.
- Aucun délai de saisie, animation décorative, disparition des labels ou
  message d'erreur qui efface le texte. Les copies anglaises suivent Live.
- Lecteurs d'écran, rendu exact de TextArea, touches réellement remontées par
  chaque terminal et contenus Unicode larges demandent une recette native
  après implémentation ; les images ne prouvent pas ces comportements.

## Réutilisation et recette future

Réutiliser les composants Textual natifs et les tokens actuels, le contexte de
projet existant, `CliContext`/facade, le dispatch partagé `/run`, le contrôleur
d'opération, les snapshots, `ActionDescriptor`, `request_action` et les APIs
d'approbation. Ne pas modifier `TextEntryScreen` globalement : filtres et
commandes ont besoin de leur comportement actuel à une ligne.

Une surface de composition dédiée peut être ajoutée dans `textual_app/` ;
elle n'est ni un nouveau renderer ni un registre de commandes. Le passage de
plusieurs critères doit emprunter le même intake que `/run` et préserver
exactement guillemets, apostrophes, retours à la ligne et chaînes commençant
par `--`. Si une chaîne d'arguments est utilisée, employer l'échappement
adapté au parseur existant, jamais une interpolation shell. Ne pas inventer
un deuxième orchestrateur de création.

Recette requise après autorisation d'implémentation : saisie multiligne et
collage ; A et B sans création intermédiaire ; critères vides/multiples ;
grille conditionnelle ; run existant ; complétion conservant l'identité ;
focus et modales ; double activation ; erreur/état incertain ; projet changé ;
ASCII/Unicode et terminaux 60/80/120/160 ; confirmation périmétrée et Research
séparée ; régressions filtres, commandes, Settings et Live. Exécuter les tests
TUI pertinents, `tests/test_cli_structure.py`, `tests/test_engine_services.py`,
la suite complète selon `06-build-test-run.md`, compileall et diff-check.

## Décision reçue en fin de revue

Le 22 octobre 2026, l'utilisateur retient **A**, sans ajustement demandé dans
les six rubriques et sans remarque générale. La décision est aussi enregistrée
dans [decisions.json](../previews/new-run-task-review/decisions.json).
Ce choix de design ne vaut ni ordre d'implémentation ni approbation moteur.
L'instruction ultérieure « Fais l'implémentation » autorise séparément la
réalisation de A et de la suite commune Task. B reste une proposition archivée.
