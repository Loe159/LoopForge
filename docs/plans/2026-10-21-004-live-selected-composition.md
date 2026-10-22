---
title: "Live — composition retenue après revue groupée"
type: ux-selection-and-refinement
date: 2026-10-21
status: design-approved-implementation-local
implementation: implemented-tested-local
parent_plan: 2026-10-20-002-run-live-visual-refinement-plan.md
---

# Composition issue du retour utilisateur

Les choix utilisateur sont enregistrés ; les ajustements sont représentés dans
la [galerie révisée](../previews/live-review-09-14/revision-01/index.html).
Le retour initial précisait : **« Ce retour ne déclenche aucune implémentation ni
approbation moteur. »** L'utilisateur a ensuite validé la composition ajustée et
demandé explicitement : **« Je valide. Passe à l'implémentation »**. Cette demande
autorise l'implémentation UI ; elle ne constitue pas une approbation d'un run.

| Lot | Choix utilisateur | Ajustement |
| --- | --- | --- |
| 9 — Execution Result | A | Reçu sans boutons de navigation ; priorité au déclenchement de l'étape suivante |
| 10 — Context | B | Sommaire et document |
| 11 — Evidences | B | Liste et reçu |
| 12 — Supervision / Workflow / métriques | A | Titres `CURRENT ACTIVITY`, `WORKFLOW`, `METRICS` en capitales |
| 13 — Commande/navigation | A | `Approval required` en orange `#FFB869` ; bloc Command Input actuel conservé |
| 14 — Cockpit | Composition | Assembler les choix ci-dessus, remplaçant l'assemblage recommandé 9C/10A/11A/12B/13B |

Les composants 1 à 7 gardent leurs validations. Le composant 8 reste en l'état.

## Execution Result : information et prochaine action

Le reçu A garde son cadre, les résultats disponibles et la prochaine étape connue.
Les boutons `View changes` / `View evidences` en sont retirés. Le menu fixe des
vues permet toujours de consulter Changes et Evidences, sans duplication dans
la chronologie. Cette décision ne retire pas les contrôles propres aux vues,
par exemple `Open artifact` dans Evidences B.

L'utilisateur privilégie le déclenchement de la suite. **Interaction validée
dans les maquettes révisées : une seule action moteur dans un bandeau
persistant au-dessus du Command Input**, également visible quand le run est prêt
pour sa prochaine étape. Le reçu ne contient pas un deuxième déclencheur.

Exemple fictif : après Implementation, le reçu constate `Agent finished` et
`Verification pending`. Le bandeau annonce `Next step · Verification` et affiche
`Ctrl+Enter Generate the patch and run deterministic checks`, libellé réellement
fourni par la guidance moteur. Il reste disponible en consultant Evidences.
Cette disposition est implémentée localement sans changement d'autonomie.

### État existant vérifié dans le code

- `ActionDescriptor` provient de la guidance moteur via `action_descriptors`.
- `action_run_required_action` appelle déjà `request_action(shell.run.next_action)`.
- `request_action` conserve les confirmations requises par le moteur.
- `_render_run` n'affiche aujourd'hui le bandeau que pour `needs_human` ou
  `blocked`. Une action Ready peut donc avoir un raccourci sans bandeau visible.
- `RunRequiredAction.update_action` emploie actuellement `Approval required`
  pour toute action non bloquée. Une future présentation Ready doit afficher
  `Next step`, sans lui donner artificiellement le statut d'approbation.

### Contrat pour une implémentation ultérieure

- Réutiliser `RunRequiredAction`, `ActionDescriptor`, `request_action` et le
  dispatch partagé. Aucun deuxième registre, bouton d'exécution dans le reçu,
  raccourci concurrent ou modification des transitions moteur.
- Afficher seulement l'action courante éligible et disponible. Aucune suite
  n'est déduite du texte de l'agent, du dernier outil ou d'un simple artefact.
- Pendant une opération active, aucune action Next step anticipée ni double
  déclenchement. Sans action éligible, aucun contrôle factice ou bouton inerte.
- Le bandeau concerne le run courant. Consulter un ancien stage/attempt ne
  redirige pas l'exécution ; l'identité du run courant et la distinction entre
  lecture historique et état moteur restent explicites.
- L'activation explicite passe par les préconditions et confirmations
  existantes. Pas de démarrage automatique, ni approval ajoutée au résultat.
- En approbation : `Approval required` reste orange. En blocage : conserver
  le bandeau et les seules actions réelles, sans Retry inventé.
- L'action avec un libellé long peut occuper une ligne supplémentaire ; la
  maquette utilise six lignes pour le panneau afin de conserver le libellé
  moteur et `Ctrl+K Other actions` sans les tronquer. Le contenu défile avant
  de sacrifier le champ de commande ou la navigation.

## Command Input : conserver le composant actuel

Conserver `RunCommandBar` et `HomeCommandInput`, leur cadre lavande, le fond
command-slate, le titre `Command Input`, la ligne de saisie et les suggestions
`/run   /status   /actions   /config`. Pas de dock réduit ni de nouvelle saisie
concurrente. L'orange vise le titre d'approbation ; il ne recolore pas la commande.
Le texte sans slash demeure inerte et le champ reste visible avec le bandeau.

## Context B, Evidences B et supervision A

Le sommaire de Context et la liste d'Evidences appartiennent à la vue centrale,
sans remplacer la supervision à droite. Les états d'ouverture, le focus et le
périmètre stage/session/attempt sont conservés. Le prompt brut reste littéral et
les niveaux de preuve distincts. Aucun élargissement des accès de lecture.

Les panneaux carrés de la supervision A portent les titres en capitales. Les
TODO restent sous leur étape et proviennent de la session sélectionnée ; leur
complétion n'est pas déduite de la fin de l'agent. La fixture du reçu terminé
contient explicitement quatre TODO complétés, d'où son compteur 4/4 fictif.
La navigation des quatre vues reste fixée au bas de la supervision.

## Vérification de l'implémentation

Contrôles de référence ; les résultats réellement obtenus et les captures sont
consignés dans le [rapport d'implémentation](../previews/live-selected-implementation/README.md) :

- Ready/Verification et Ready/Review : bandeau visible, un seul dispatch de
  l'action moteur, confirmations maintenues selon le profil.
- Approval : titre orange ; refus, annulation ou précondition invalide ne
  déclenchent pas l'étape suivante.
- Opération active, action absente/indisponible, run changé et lecture d'une
  ancienne tentative : aucun déclenchement erroné ni action historique.
- Command Input : même composant, slash dispatch existant, texte libre inerte.
- Context/Evidences B : navigation, focus, Markdown sûr, Raw, reçus périmés et
  isolation des tentatives.
- Dimensions 60/80/120/160 et faible hauteur : action, commande et navigation
  accessibles ; titres en capitales, TODO et sélection préservés.
- Pilotes Textual pertinents, captures réelles, `python -m unittest` et
  `git diff --check` avant toute affirmation de réalisation terminée.
