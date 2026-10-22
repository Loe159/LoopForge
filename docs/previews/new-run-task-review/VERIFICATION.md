# Inspection de conception — New Run / Task

Date : 21 octobre 2026. Périmètre : maquettes et galerie de revue.

Mise à jour du 22 octobre : A a été retenu, puis une instruction séparée a
autorisé son implémentation. Ce journal conserve les constats de la phase de
conception. La [revue de la livraison native](../new-run-task-implementation/REVIEW.md)
documente séparément le code et les tests ; le statut courant est enregistré
dans `decisions.json`.

## Références et méthode

Lecture de PRODUCT.md, DESIGN.md, AGENTS.md, des documents agent 01/03/04/05/06/07,
du parcours actuel et des contrats moteur. Skill Impeccable : principes Operate,
préparation de parcours, craft floor et inspection visuelle des états proposés.
Le choix de montrer A et B suit la demande explicite de l'utilisateur.

Il s'agit d'une inspection par l'auteur, pas d'une revue indépendante. Le
détecteur web Impeccable n'a pas été utilisé pour certifier des images terminal :
il ne peut pas vérifier le comportement natif d'une maquette statique.

## Contrôles des livrables

- 19 maquettes en PNG/SVG/texte : décodage des images, XML des SVG, dimensions,
  lignes et largeurs de grille ; les scènes 60 colonnes utilisent un chrome ASCII.
- Capture du `TextEntryScreen` actuel réellement rendue dans Textual, au-dessus
  d'une fixture synthétique. Aucun run créé, aucun agent exécuté.
- Inspection de la planche et des fichiers individuels, puis confirmation des
  corrections : curseur sans perte d'un caractère, description conservée en
  petit terminal, critères sous le pli annoncés, contrastes des labels et
  bordures, profil cohérent dans la scène subjective, commande et navigation
  du run conservées dans la scène Task.
- Galerie HTML/JS locale : liens et ressources existants, IDs uniques, script
  syntaxiquement valide ; aucune dépendance distante ni choix présélectionné.
- Contrôles dans Firefox headless : agrandissement, navigation, zoom, retour du
  focus, génération du retour avec vraies nouvelles lignes, export reflétant
  les choix courants, rechargement sans persistance, chargement des images.
  Aucun appel HTTP(S) de la galerie. L'export est intercepté dans la recette
  pour vérifier son nom et son contenu préparé sans le soumettre à un service.
- Galerie vérifiée en 1440 pixels et dans un viewport intégré de 390 pixels
  (Firefox impose ici une fenêtre externe d'au moins 500 pixels). Le viewport
  de la page examinée, pas seulement la taille demandée à la fenêtre, est contrôlé.
- Huit cas de `validate_task_definition` vérifiés en lecture seule : tâche ou
  critère manquant, un ou plusieurs critères, profil supervised/autonomous,
  besoin conditionnel de grille subjective. Aucune règle métier réimplémentée.
- `git diff --check` et contrôle des espaces des nouveaux documents.

Les ratios minimaux calculés pour les rôles de texte sur la surface de saisie
dépassent 4,5:1 ; les bordures de saisie inactives dépassent 3:1. Ils concernent
les couleurs de la proposition et ne certifient pas tous les thèmes terminaux.

## Corrections faites pendant la préparation

Le contrôle navigateur a détecté une nouvelle ligne non échappée dans le script
générateur de la galerie : corrigée, puis vérifiée avec `node --check` et les
contrôles d'interaction. Deux ajustements du script de recette, sans changement
produit, ont été nécessaires : compter 20 aperçus pour 19 scènes distinctes et
intercepter l'export dans le contexte JavaScript de la page.

Les hypothèses UX dangereuses ont été retirées : « Save proof » devient
« Save criterion », aucun bouton d'édition globale d'un run existant, grille
subjective recueillie avant création, approbation distincte de la création et
de Research. Le plan précise les cas de changement de contexte et d'issue
incertaine avant un éventuel réessai.

## Limites de ce résultat

Aucun code sous `src/`, test produit ou réglage moteur n'a été changé pendant
cette préparation. La suite complète n'a pas été relancée pour ces seuls
documents et maquettes. Ses erreurs préexistantes de la revue Live ne sont pas
présentées comme résolues par ce travail.

La navigation, le défilement, les raccourcis et les états du futur formulaire
sont **spécifiés**, pas exécutés par les images. Leur recette Textual, le
collage de grands textes, les caractères Unicode larges, les lecteurs d'écran,
les différences entre terminaux et les courses de création restent à vérifier
après autorisation d'implémentation. Aucune certification d'accessibilité ni
validation de l'ensemble du moteur n'est déduite de cette inspection.

Journaux de préparation : `/tmp/loopforge-new-run-browser-check.log` et
`/tmp/loopforge-new-run-assets-check.log`. À cette date de préparation, le
statut de décision était en attente ; ces contrôles n'accordent aucune autorité
de workflow.
