# Live — revue groupée des composants 9 à 14

**Statut : revue initiale archivée ; retour utilisateur enregistré.**

**Choix reçus : 9A / 10B / 11B / 12A / 13A, composition intégrée.**
Voir la [composition ajustée après retour](revision-01/index.html) et les
[décisions](../../plans/2026-10-21-004-live-selected-composition.md).
L'assemblage recommandé plus bas décrit la proposition initiale et est remplacé
par les préférences reçues. Le retour n'autorise aucune implémentation.

[Ouvrir la galerie locale](index.html). Elle fonctionne depuis un fichier local,
sans serveur ni dépendance externe. Les composants 1 à 7 gardent leurs décisions
validées ; **Error / Warning / Unknown reste en l'état** (décision `03034b7`).

La consigne utilisateur du 21/10/2026 remplace les arrêts entre composants :
proposer d'autres variations d'Execution Result, terminer les prochains composants,
puis regrouper la validation à la fin. Ce dossier termine la phase de maquettage ;
il n'autorise pas encore l'implémentation.

## Contenu et revue

31 maquettes en PNG, SVG et texte : 7 pour Execution Result, 4 par composant
10 à 13 et 8 scènes intégrées. A/B d'Execution Result sont conservées pour
comparaison ; C/D/E sont les nouvelles pistes. Chaque image indique qu'il s'agit
de données fictives. Ce ne sont pas des captures de l'application.

| Lot | Variantes | Proposition recommandée pour l'assemblage |
| --- | --- | --- |
| 9 — Execution Result | [A : reçu encadré](assets/09-a-120.png), [B : sections](assets/09-b-120.png), [C : deux filets](assets/09-c-120.png), [D : résumé dépliable](assets/09-d-120.png), [E : suite en premier](assets/09-e-120.png) | C : continuité avec le flux et faits toujours visibles |
| 10 — Context | [A : sections de lecture](assets/10-a-120.png), [B : sommaire et document](assets/10-b-120.png) | A : neuf sections sans ajouter une colonne de navigation |
| 11 — Evidences | [A : registre par niveau](assets/11-a-120.png), [B : liste et reçu](assets/11-b-120.png) | A : provenance proche de chaque niveau de preuve |
| 12 — Supervision | [A : panneaux structurés](assets/12-a-120.png), [B : titres sobres](assets/12-b-120.png) | B : plus de place pour Workflow et ses TODO |
| 13 — Commande/navigation | [A : dock encadré](assets/13-a-120.png), [B : dock réduit](assets/13-b-120.png) | B : action et commande explicites avec moins de hauteur |
| 14 — Cockpit intégré | [Running](assets/14-running-120.png), [fin d'exécution](assets/14-finished-120.png), [Blocked](assets/14-blocked-120.png), [Approval](assets/14-approval-120.png) | Assemblage provisoire 9C / 10A / 11A / 12B / 13B |

Ces recommandations ne présélectionnent pas les champs de la galerie. Les choix
peuvent être combinés indépendamment. Agrandir une image ouvre une lecture à
taille réelle ; les flèches parcourent les maquettes et Esc revient à la galerie.

Les avis et notes restent en mémoire dans l'onglet. « Préparer mon retour »
assemble un texte à copier ; « Exporter le retour en .txt » le télécharge
uniquement sur demande. Il n'y a ni envoi, ni stockage automatique, ni action
sur un workflow. Fermer ou recharger la page perd les champs non exportés.

## Décisions de conception soumises

### 9 — Fin d'exécution

C conserve les faits d'A entre deux filets. D ne replie que les faits secondaires :
fin de l'agent, vérification, suite et liens restent visibles. E place la prochaine
étape avant le bilan, sans bouton d'exécution additionnel. Une fin de session ne
prouve pas une réussite. Un contrat validé exige un reçu positif explicite ;
l'extraction de `result.json` ne suffit pas. Les variantes C/D sont aussi dessinées
à 80 colonnes, D avec les détails ouverts.

### 10 — Instructions réellement fournies

A garde une vue verticale : Mission & Role ouverte, System Instructions,
Injected Documents, Environment & Git, Pack/Skills/Tools, Permissions & Security,
Output Contract, Validation & Limits et Raw Prompt. Permissions et contrat ont
un résumé visible. B ajoute un sommaire local à Context et affiche le document
sélectionné au centre ; la supervision reste à droite.

Le Markdown lisible s'applique aux documents, pas au Raw. Les sources sont celles
du manifeste capturé, jamais des fichiers actuels relus pour fabriquer un ancien
prompt. Le prompt exact reste une source distincte ; affichage borné ou redaction
sont signalés dans la vue demandée. Une capture ancienne sans manifeste reste
`derived`. Un hash invalide refuse la confiance ; aucune reconstruction.

Les maquettes utilisent le champ réellement disponible « Runner timeout
requested: 600 seconds », sans prétendre prouver les flags de sandbox du harness.
Le cas Research distingue explicitement détection des mutations après exécution
et prévention technique des écritures.

### 11 — Niveaux de preuve

L'ordre reste Livrables → Contrats → Tests & vérifications → Décisions humaines.
A les présente dans le flux ; B fournit une liste et un reçu consultable. Lire le
JSON d'un artefact ne transforme pas ses affirmations en résultats de tests.

Chaque fait conserve sa provenance et son périmètre lorsqu'ils sont connus.
L'absence de reçu de contrat n'est pas présentée comme un succès. Les comptes
de tests exigent une source structurée fiable. Les reçus anciens restent
consultables mais ne sont pas attribués au candidat courant ; un résultat périmé
n'est pas affiché comme un `Passed` courant. Une vérification réussie ne donne
aucune approbation humaine ni autorité de publication.

### 12 — Supervision permanente

A conserve des panneaux carrés ; B utilise des titres et séparateurs sobres.
Le contenu comparé est identique : Planning consulté pendant Implementation.
La sélection de lecture et l'activité moteur gardent des repères distincts.
La sélection sans focus reste discrète ; le focus clavier utilise l'inversion
lavande. La progression TODO est exclusivement celle de la session sélectionnée,
imbriquée sous son étape, conformément au composant 6 validé. Aucun bloc Plan
autonome n'est réintroduit dans Live.

L'ordre reste activité/problèmes existants, Workflow, métriques connues, puis
navigation fixe au bas. Le traitement Error / Warning / Unknown n'est pas
redessiné. Les informations et le Workflow peuvent défiler sans déplacer les
quatre vues. Tokens/coût absents sont omis, sans faux zéro. À 80 colonnes,
l'overlay existant conserve le même arbre et le menu à son pied.

### 13 — Action, commande et lecture

A sépare les deux zones par des cadres ; B réduit la hauteur avec des filets.
Les modes Focused/All/Raw restent au-dessus du flux Live, sans onglets de vues
concurrents. La sélection de tentative/session précède le contenu et garde son
périmètre en changeant de vue. Planning/Research/Review utilisent Session quand
aucun vrai numéro de tentative d'implémentation n'existe.

Le bandeau reste au-dessus de la commande. `Ctrl+Enter Approve plan` n'existe
que dans la fixture où le moteur propose cette action ; un blocage sans action
primaire ne reçoit pas de bouton Retry/Approve inventé. Les confirmations et
reçus existants restent nécessaires dans le produit. La commande reste accessible,
et un texte sans slash reste inerte.

Bindings réutilisés et vérifiés dans le code : F4 détail, F6 supervision/vues,
Ctrl+K actions, Ctrl+Enter action officielle, End suivi. Aucun Alt+1…4 nouveau.
Le suivi suspendu reste explicite ; son compteur n'agrège pas les anciennes
sessions. Raw reste littéral et décrit les bornes de la capture.

### 14 — Assemblage, pas encore recette runtime

Les scènes combinent les propositions recommandées avec les composants validés.
Elles couvrent Running, fin d'exécution avec run encore prêt pour Verification,
Blocked et Approval. S'y ajoutent 160 colonnes, Approval à 80 colonnes,
Blocked en ASCII à 60 × 24 et Running à 120 × 24.

Ce sont des préfigurations du cockpit : les positions et interactions devront
être confirmées par les pilotes Textual après implémentation. La recette réelle
ne peut pas être déclarée terminée à partir de dessins. Ni le moteur, ni les
permissions, ni les preuves, ni les composants déjà validés ne changent ici.

## Sources et vérification

- [DESIGN.md](../../../DESIGN.md) : grille terminal, surfaces, palette et focus.
- [Plan UX parent](../../plans/2026-10-20-001-run-live-context-ux-plan.md) : D01–D31 et décision de conservation du composant 8.
- [Suivi de la refonte](../../plans/2026-10-20-002-run-live-visual-refinement-plan.md).
- [Plan TODO validé](../../plans/2026-10-21-003-plan-todo-in-workflow.md).
- Contrats existants inspectés : `RunSnapshot`, `RunContextSnapshot`,
  `RunEvidencesSnapshot`, `RunChangesSnapshot`, `StageView`,
  `RunRequiredAction`, `RunDocumentView` et `RunSupervisionScreen`.

Les fichiers image et les largeurs des grilles sont contrôlés séparément de
l'application. Le journal de vérification du dossier indique les contrôles
réellement exécutés. Aucune suite produit n'est présentée comme exécutée pour
ces seuls documents et maquettes.
