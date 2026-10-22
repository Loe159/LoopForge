# New Run / Task — correction clavier et initialisation

22 octobre 2026. Composition A et tailles d'écran acceptées par l'utilisateur.
Il demande ensuite Tab entre les champs, un critère vide disponible à la fin
et l'initialisation automatique du projet pour créer son premier run.

## Comportement livré

- Tab / Maj+Tab parcourent les éditeurs puis les boutons. La protection contre
  les raccourcis du dashboard préserve maintenant les actions Textual de focus,
  y compris dans le dialogue d'abandon. Entrée reste une nouvelle ligne dans
  un éditeur ; Ctrl+Entrée soumet ; Entrée active un bouton sélectionné.
- Écrire dans le dernier critère fait apparaître le suivant sans déplacer le
  curseur. Supprimer ce dernier champ vide en recrée un. Add criterion rejoint
  le champ vide existant ; les boutons Remove restent accessibles au clavier.
- Les critères vides ou composés d'espaces sont filtrés du brouillon soumis.
  La complétion d'un run enregistré conserve son opération à un seul critère.
- Le formulaire charge les valeurs moteur par défaut d'un projet non initialisé
  sans l'écrire. Create run initialise LoopForge via `initialize_project`, puis
  crée le run via `create_run`. Le slash `/run` partage cette orchestration.
  Un projet déjà initialisé garde sa configuration. Il n'y a aucune création
  automatique de dépôt Git, approbation Task ou exécution Research.

## Vérification ciblée observée

`PYTHONPATH=src .venv/bin/python -m unittest tests.test_task_composer tests.test_cli_structure tests.test_engine_services`

107 tests passent, sans erreur ni échec. Le fichier Task comprend désormais
20 tests, dont cinq nouveaux cas. Ils couvrent notamment :

- saisie et création par Tab depuis un projet non initialisé, puis contrôle
  du contrat enregistré et de l'absence d'approbation/exécution ;
- ouverture sans initialisation et cohérence des valeurs moteur annoncées ;
- Tab / Maj+Tab entre éditeurs et accès à chaque bouton, sans raccourci global
  interceptant le texte ;
- rubrique conditionnelle et choix d'abandon accessibles au clavier ;
- ajout automatique sans vol de focus, suppression du dernier champ vide et
  exclusion des blancs à l'enregistrement ;
- focus dans le champ et footer utilisable après redimensionnement à
  48/52/60/80/100/120/160 colonnes, hauteur de 24 lignes.

Un essai natif supplémentaire vérifie les clics dans un critère et, après
défilement jusqu'au bouton, sur Add criterion, avec conservation du texte et
focus sur le champ vide. Une première tentative de clic avant la fin du
défilement visait un bouton encore caché par le footer ; l'essai corrigé attend
le défilement et clique dans la région visible du bouton.
Compilation et `git diff --check` passent. Le détecteur Impeccable ne signale
rien sur les deux modules UI modifiés ; cette analyse mécanique de code Python
ne remplace pas les tests Textual ni une validation utilisateur.

Un deuxième passage complet a révélé une course de fermeture dans le test
préexistant `test_home_create_opens_task_and_approval_never_starts_research` :
la sauvegarde d'approbation sur disque était observée avant la publication de
son snapshot UI ; le teardown détruisait les enfants de RunHeader pendant
qu'un message de rafraîchissement restait en attente. Le test attend désormais
la fin d'opération **et** l'approbation publiée dans StateStore, puis draine les
workers avant de fermer l'application. Le nouveau parcours de premier run
draine également ses workers. Aucun délai arbitraire ni skip n'est ajouté.
Les deux parcours passent ensuite quatre fois chacun : huit essais, zéro
erreur/échec (`/tmp/loopforge-task-keyboard-route-repeat.log`).

## Suite complète après correction de synchronisation

Deux passages complets consécutifs sur les sources finales :

| Passage | Tests | Durée | Échecs | Erreurs | Skips existants |
| --- | --- | --- | --- | --- | --- |
| `/tmp/loopforge-task-keyboard-full-3.log` | 787 | 273,832 s | 0 | 3 | 3 |
| `/tmp/loopforge-task-keyboard-full-4.log` | 787 | 278,312 s | 0 | 3 | 3 |

Les trois erreurs proviennent des trois sous-cas de
`test_readonly_research_retains_invalid_candidates_and_allows_retry` : lecture
de `research-candidate-001.md` à son ancien emplacement après archivage.
La [revue initiale](../REVIEW.md) documente leur reproduction sur la baseline
avant les refontes. Le code d'archivage n'est pas modifié dans ce correctif.
La suite complète n'est donc **pas verte** ; les quatre tentatives et les hashes
des sources testées sont conservés dans [checks.json](checks.json).

La revue finale conserve le correctif demandé et les attentes de synchronisation
de tests, sans élargir le périmètre à l'archivage. Aucun test n'est désactivé.
Le commit est local ; aucune nouvelle demande de push n'a été reçue.

## Inspection native

Captures synthétiques après trois Tab : le troisième critère est vide et
possède le focus. Le footer reste visible et le formulaire défile pour suivre
le champ actif. Les données sont des fixtures, sans run ni approbation réelle.

- [48 × 24](criteria-48x24.png), [SVG](criteria-48x24.svg).
- [120 × 40](criteria-120x40.png), [SVG](criteria-120x40.svg).
- [Régions et contenu relevés à cinq tailles](layout.json).

Le thème ANSI utilisé par les captures produit un rendu monochrome. Le layout
validé, les styles de champs et les tokens de couleur ne sont pas modifiés.
Inspection Impeccable et revue du diff réalisées dans le même fil ; aucune
revue indépendante n'est revendiquée.

Prévisualisation sans écriture :

```sh
PYTHONPATH=src .venv/bin/python tools/demo_task_composer.py --state filled
```

Dans l'application réelle, sélectionner un projet, ouvrir New Run, saisir la
tâche, Tab, saisir un critère, Tab. Le champ suivant est prêt ; Create run
initialise le projet si nécessaire. L'approbation Task demeure une action
distincte. Confirmation utilisateur de ces corrections encore attendue.
