---
title: "Run TUI — spécification UX validée : Live / Context / Changes / Evidences"
type: ux-implementation-plan
date: 2026-10-20
status: design-approved
implementation: not-started
decision_source: user-interview-2026-10-20
---

# LoopForge — refonte Run / Live : spécification UX et plan d'implémentation

> **Statut : design validé, non implémenté.** Ce document est la référence pour la refonte du Run TUI. Il remplace les arbitrages UX encore ouverts dans sa version initiale du 20 octobre 2026. **Aucun changement de comportement moteur, de politique de sécurité ni de permission n'est autorisé par cette spécification.**
>
> Sources du dépôt : [design system](../../DESIGN.md), [observation des agents actuellement implémentée](../decisions/agent-run-observation.md), [widgets Textual](../../src/loopforge/cli/textual_app/widgets.py), [présentation du run](../../src/loopforge/cli/textual_app/run_presenter.py). Les exemples de données ci-dessous sont **fictifs**.

## 1. Vision, portée et invariants

LoopForge orchestre des workflows supervisés en cherchant à minimiser l'attention et les interventions humaines. La page Run doit permettre de savoir, sans lire un journal brut :

1. **Ce qui se passe maintenant** : étape, tentative, agent et activité courante.
2. **Ce que l'agent fait réellement** : messages, outils, sous-agents observés et résultats, dans l'ordre de leur émission.
3. **Ce qui lui a été donné** : rôle, mission, documents, limites, permissions effectivement imposées.
4. **Ce qui a changé** : diff de la tentative sélectionnée et cumul du run.
5. **Ce qui est prouvé** : artefacts extraits, contrats validés, contrôles déterministes, approbations humaines.
6. **Ce qui exige une intervention** : prochaine action *autorisée par le moteur*, visible et contrôlable sans masquer le journal.

Le produit reste une **TUI Textual terminal-native** et non une interface web : palette de `DESIGN.md`, monospace, cellules carrées, densité équilibrée « façon Codex », clavier en premier, souris possible, labels lisibles sans dépendre seulement des couleurs.

**Invariants :**
- Le terminal natif du harness reste **séparé et interactif** ; Live observe **la même exécution** et ne démarre jamais un second agent pour l'affichage.
- Le moteur seul détermine les étapes, statuts, actions et approbations. Le harness ne peut pas valider lui-même un contrat LoopForge.
- Le prompt complet quitte Live mais reste inspectable, **identique au prompt réellement envoyé** (sous réserve de redactions d'affichage explicitement liées à la sécurité).
- L'ordre des événements et leur identité source restent conservés ; les regroupements sont des **projections réversibles**.
- Aucune métrique, durée, hiérarchie de sous-agents, erreur résolue, permission ou réussite ne doit être **inventée**.
- Changer d'onglet, de tentative, d'étape ou de mode de lecture est une **lecture seule**.
- En cas de donnée facultative non fournie, **ne pas afficher de panneau d'alerte « observation partielle »** ; omettre simplement le champ. Une erreur effective et un état d'outil sans résultat ont, eux, un statut honnête.
- Recherche textuelle et filtres avancés sont **explicitement hors périmètre pour cette itération**.

## 2. Registre exhaustif des décisions UX

Chaque ligne ci-dessous provient de l'interview utilisateur et fait autorité pour le design. La dernière décision (D31) corrige les premières maquettes : les quatre vues sont **en bas à droite**, pas en onglets au-dessus du flux.

| ID | Sujet | Décision retenue |
| --- | --- | --- |
| D01 | Philosophie | **Hybride** : flux conversationnel central + supervision permanente à droite. |
| D02 | Détail du flux | **Conversation avec outils condensés** ; messages prioritaires, opérations compactes. |
| D03 | Panneau droit | **Supervision permanente**, pas d'inspecteur contextuel. |
| D04 | Sous-agents | **Blocs repliables** avec activité enfant si la relation est observable. |
| D05 | Historique | **Flux par étape**, anciennes étapes consultables via le workflow. |
| D06 | Vues | **Quatre vues distinctes** : Live, Context, Changes, Evidences. |
| D07 | Supervision | **Équilibrée** : workflow, activité, problèmes et métriques utiles. |
| D08 | Outils | **Dépliage inline + vue plein écran** pour sorties longues. |
| D09 | Scroll | **Follow intelligent** : suit le bas, se suspend quand on inspecte ou remonte. |
| D10 | Human-in-the-loop | **Bandeau contextuel fixe** juste au-dessus du champ de commandes. |
| D11 | Context | **Contexte structuré** avec accès au prompt brut exact. |
| D12 | Changes | **Git par tentative + cumul du run**. |
| D13 | Evidences | **Tableau de validation structuré** : livrables, contrats, tests, décisions. |
| D14 | Terminal | **Harness dans un terminal séparé** ; pas de PTY embarqué. |
| D15 | Problèmes | **Erreurs dans Live + résumé permanent** dans la sidebar. |
| D16 | TODO/plan | **Flux + progression compacte** si le harness l'expose. |
| D17 | Métriques | **Essentielles uniquement** : modèle, durée, tokens, coût si connu. |
| D18 | Fin d'exécution | **Carte de résultat finale** dans Live, sans changement automatique de vue. |
| D19 | Clavier | **Navigation hybride** : Tab/flèches/Enter/Esc + raccourcis ciblés. |
| D20 | Taille du terminal | **Adaptation automatique** ; sidebar masquée en mode étroit. |
| D21 | Réouverture | **Reprise intelligente** : onglet, étape, tentative, position, état follow. |
| D22 | Recherche | **Reportée** ; pas de recherche/filtres dans cette refonte. |
| D23 | Streaming | **Mise à jour en place** des appels d'outils, sans doublon. |
| D24 | Données manquantes | **Affichage silencieux** des informations non disponibles. |
| D25 | Reasoning | **Replié par défaut**, uniquement ce qui est publiquement exposé. |
| D26 | Tentatives | **Sélecteur au-dessus du flux principal** (étape dans sidebar). |
| D27 | Regroupement | **Par catégorie** : lectures/recherches consécutives ; erreurs toujours visibles. |
| D28 | Sidebar | **Activité en premier**, puis problèmes, workflow et métriques. |
| D29 | Horodatage | **Discret** : heure/durée dans détails, durée visible pour outils longs si connue. |
| D30 | Densité | **Équilibrée façon Codex** : messages espacés, outils indentés, peu de bordures. |
| D31 | Placement des vues | **Navigation Live / Context / Changes / Evidences ancrée en bas à droite de la sidebar**, comme dans l'UI actuelle ; aucune rangée d'onglets au-dessus du flux. |

**Résolution des contradictions de l'ancien plan :** toute représentation d'onglets horizontaux au-dessus de Live est obsolète ; toute proposition de recherche/filtres ou d'avertissement systématique « observation partielle » est exclue du périmètre approuvé. `Focused / All / Raw` restent des **modes de lecture** dans Live, et non des filtres de recherche.

## 3. Architecture visuelle de la page

### 3.1 Structure stable en terminal large

```text
┌ LoopForge / Project / Run #42 / Task ─────────── git:branch   Running ┐
│ ┌ MAIN (scroll indépendant) ─────────┐ ┌ RUN CONTEXT (fixe) ────────┐ │
│ │ Implementation     [Attempt 02 ▼] │ │ CURRENT ACTIVITY            │ │
│ │ Focused | All | Raw               │ │  Implementation · Codex     │ │
│ │                                    │ │  Agent TODO 3/5 (si connu)  │ │
│ │ [Live, Context, Changes ou       ]│ │  Errors / warnings (réels) │ │
│ │ [Evidences : vue sélectionnée    ]│ │                            │ │
│ │                                    │ │ WORKFLOW (navigable)        │ │
│ │ Agent messages / tools / details  │ │  ✓ Research                │ │
│ │                                    │ │  ✓ Planning                │ │
│ │                                    │ │  ◉ Implementation          │ │
│ │                                    │ │  ○ Verification            │ │
│ │                                    │ │  ○ Review                  │ │
│ │                                    │ │                            │ │
│ │                                    │ │ METRICS                    │ │
│ │                                    │ │  elapsed · tokens · cost    │ │
│ │                                    │ │                            │ │
│ │                                    │ │ (espace flexible)          │ │
│ │                                    │ ├────────────────────────────┤ │
│ │                                    │ │ > Live                     │ │
│ │                                    │ │   Context                  │ │
│ │                                    │ │   Changes                  │ │
│ │                                    │ │   Evidences                │ │
│ ├────────────────────────────────────┤ └────────────────────────────┘ │
│ │ [Required Action si nécessaire]  │                                │
│ │ / Enter a LoopForge command...   │                                │
│ └────────────────────────────────────┘                                │
└ [raccourcis contextuels] ──────────────────────────────────────────────┘
```

Le bandeau de décision, le champ de commande et les raccourcis restent attachés au bas de l'écran ; **seul le contenu de la vue centrale défile**. Le bas de la sidebar est réservé à la navigation entre les quatre vues, **dans cet ordre**. Ce menu ne défile pas avec les métriques ; la section haute de supervision peut, elle, être scrollable à faible hauteur.

Les quatre noms de vue sont des contrôles actifs au clavier et à la souris ; les labels inactifs « unavailable » de l'implémentation actuelle disparaîtront au terme du chantier. Le menu de droite ne change pas quand on passe d'une vue à une autre.

### 3.2 Identités et sélection

La sélection courante est `project_id + run_id + stage_id + attempt_id + session_id` **quand chaque composant existe**. Ne pas confondre :
- Numéro du run (identité du workflow) et numéro de tentative (réessai local).
- Étape du moteur et tentative d'implémentation ; certaines étapes non-implémentation ont des **sessions** sans numéro de tentative d'implémentation.
- Sélection de lecture et état *effectivement actif* dans le moteur.

**Workflow dans la sidebar** : Enter sur une étape navigue vers son historique ; la tâche effective continue, sans être re-ciblée par cette lecture. L'étape en cours et l'étape sélectionnée doivent avoir des indications visuelles **distinctes**.

**Tentative** : au-dessus du flux, sélecteur `Attempt 02 ▼` quand cette étape en comporte plusieurs ; `No attempt yet` si aucune. Pour Research / Planning / Review, employer un libellé `Session` ou `Execution` si les données n'ont pas de véritable attempt number. Le sélecteur s'applique aussi aux vues Context, Changes et Evidences.

**Header** : projet, numéro du run, tâche tronquée proprement, branche connue, état officiel du run. Les événements détaillés portent l'identité de la sélection, et jamais celle d'un autre run.

### 3.3 Ordre exact des informations dans le panneau droit

1. **CURRENT ACTIVITY** — statut réel ; étape, harness, tentative ; TODO de l'agent compact si fourni ; problèmes réels en priorité.
2. **WORKFLOW** — étapes et statuts vérifiés ; sélection au clavier/souris ; activité et progression *moteur* distinctes du plan de l'agent.
3. **METRICS** — durée, modèle, tokens, coût **seulement si renseignés** (pour ne pas afficher de chiffres inventés).
4. **NAVIGATION FIXE EN BAS** — `Live`, `Context`, `Changes`, `Evidences`. Les informations du haut ne peuvent pas pousser cette navigation hors de l'écran.

Lors d'un blocage, une demande de décision prévaut sur l'ordre visuel usuel. Les informations optionnelles peuvent être compressées, pas le menu de navigation.

### 3.4 Adaptation 60 / 80 / 120 / 160 colonnes

- **120–160 colonnes** : deux panneaux, menu de vues fixé en bas à droite.
- **~80 colonnes** : contenu principal en largeur complète, sidebar masquée ; petite barre `Stage · Status · Attempt · [Supervision]` ; un raccourci ouvre un écran/panneau temporaire de supervision **dont la navigation entre vues reste en bas**.
- **~60 colonnes** : titres raccourcis, descriptions wrap, outils une ligne quand possible, visualisation des détails scrollable. Ni approbation ni champ de commandes ne disparaît.
- Les seuils exacts sont à fixer par tests Textual sur le contenu réel, pas par une largeur rigide non vérifiée ; une faible **hauteur** doit aussi préserver action + commande + navigation accessible.
- Aucun élément ne doit imposer un débordement horizontal pour pouvoir être utilisé.

## 4. Spécification de Live

### 4.1 Règles de lecture

- **Focused (défaut)** : messages de l'agent visibles, outils d'une ligne, regroupements de lectures/recherches consécutives, erreurs/approbations/résultats toujours visibles.
- **All** : tous les événements **structurés et conservés** de la session, dans leur ordre original ; mêmes objets mais sans regroupement masquant les actions.
- **Raw** : journal source conservé (`agent-transcript.log` ou `adapter.stdout` selon le chemin), affiché littéralement avec bornes et provenance lorsqu'il est incomplet. **Raw ne signifie pas journal natif intégral** si la capture a été bornée.

Les modes ne changent ni l'exécution ni la conservation. Ils ne sont **pas** des filtres par type, période ou texte. Les erreurs et gates ne sont jamais perdues du fait d'un regroupement.

### 4.2 Taxonomie des entrées et rendu

| Entrée | Focused par défaut | Dépliage / détail |
| --- | --- | --- |
| Séparateur d'exécution | `Implementation · Attempt 02 · Codex` | Statut, identité, timestamps connus. |
| Initialisation agent | Une ligne courte `Agent initialized` si observée | Lien vers Context ; pas de prompt complet dans Live. |
| Message agent | Corps lisible, paragraphes légèrement espacés | Contenu réellement émis, sans paraphrase LLM ajoutée. |
| Reasoning | `Reasoning ▸` discret, **fermé** | Texte observable uniquement ; pas de thinking caché/inféré. |
| Plan / TODO | TODO natif si disponible ; résumé 3/5 dans la sidebar | Liste originale et statuts fournis par le harness. |
| Read / Search | `Read 8 files ▸` / `3 searches ▸` si typés | Tous les appels enfants, arguments et résultats identifiés. |
| Shell / tool / MCP | `Shell · pytest tests/ ▸` + statut | Entrée, sortie, appel ID, exit code si fourni, heure/durée si disponibles. |
| Délégation | `Sub-agent · Code review ▸` si lien fiable | Sous-flux lié à cette délégation, pas de relation devinée. |
| File change déclaré | `File change · …` | Déclaration du harness ; renvoi vers Changes pour la preuve Git. |
| Warning / error | Visible en ligne, priorité à la lisibilité | Motif observable, outil/source/état exact ; saut depuis sidebar. |
| Contract / check | Statut uniquement depuis validateur/moteur | Résultat, conditions, lien Evidences. |
| Final answer / livrable | Message final original + référence au livrable | Texte/artefact dans la source appropriée. |
| Fin d'exécution | **Carte finale** dans la chronologie | Résultat moteur, validations, changements prouvés, suite réelle. |

Le **reasoning replié** conserve son emplacement d'origine, sans dérouler sa prose par défaut. Le reste du flux reste lisible et densément monospace, avec peu de conteneurs bordés.

### 4.3 Outils : identité, rendu incrémental et détail plein écran

Pour chaque appel, préférer l'identifiant natif `call_id` quand il existe. L'état est `running`, `completed`, `failed` ou `unknown`, jamais une réussite inférée parce qu'un spinner s'arrête. Une mise à jour start/result remplace **l'état du même widget**, sans doubler la ligne. Deux appels parallèles au même nom restent deux appels distincts.

- `Enter` sur un outil : ouvrir/fermer les paramètres et sorties **inline**.
- Un raccourci contextualisé ouvre le **détail plein écran** (notamment logs volumineux), en lecture seule ; `Esc` revient à la même ligne, avec scroll et focus conservés.
- L'outil peut changer de `running` à `completed` ou `failed` pendant qu'il est ouvert, mais l'utilisateur garde sa position.
- Un outil à sortie tronquée montre **uniquement la sortie retenue**, pas un faux texte « complet ».
- Si la fin du processus arrive sans résultat d'outil : `unknown`, ou `No result received` dans son détail, **pas** d'icône verte.
- Heure exacte et durée détaillée ne se présentent que si elles sont disponibles ; les outils longs peuvent montrer leur durée dans leur ligne compacte si elle est mesurée.

### 4.4 Regroupement par catégorie

Regrouper **seulement** des appels consécutifs dont la catégorie est connue avec certitude : `Read N files`, `N searches`. Les autres outils (commandes, writes, tests, MCP non classés) restent indépendants. Le regroupement est déterministe et réversible ; l'expansion révèle tous les éléments dans leur ordre original.

Interrompre systématiquement un groupe à l'arrivée d'un message agent, d'une erreur, d'un warning, d'une transition d'étape ou d'une décision. Ne jamais masquer une erreur dans un groupe fermé, ni créer une catégorie en interprétant librement un texte shell.

### 4.5 Sous-agents

Affichage approuvé : une délégation observée donne un **bloc repliable**, avec titre/agent/état connu et liste d'événements enfants **si le harnais expose effectivement la relation**. Le lien parent-enfant exige des IDs/corrélations fiables. Un appel d'outil « spawn » sans événements enfants inspectables peut être présenté comme un appel de délégation, **mais pas comme un sous-flux complet**. Aucune arborescence n'est inventée à partir du texte d'un message.

Ne pas ajouter un orchestrateur LLM ni une session auxiliaire pour reconstituer les sous-agents. Les données actuellement non capturées nécessitent une extension explicite des adapters.

#### Décision de design validée — Variante A « Flux compact » (21 octobre 2026)

**Statut du composant Sous-agent / Délégation : design approuvé ; implémentation et acceptation visuelle du composant réel en attente.** La validation concerne exclusivement sa présentation dans Live et n'autorise ni travaux sur les composants voisins, ni changement de comportement moteur, ni push.

- **Ligne repliée par défaut** : `▸ Sub-agent · Security review    ◌ Running` (titre natif et statut connu seulement). Alignement monospace, sans carte bordée ; focus lavande inversé seulement lorsque la ligne possède le focus, fond discret hors focus.
- **Expansion inline** : une seule indentation et un trait vertical neutre pour distinguer les événements réellement enfants. Montrer mission native si disponible, messages d'agent, appels d'outils/Read/Search, reasoning public replié et réponse native finale. Conserver l'ordre d'origine et permettre de déplier chaque outil ; aucune synthèse IA nouvelle.
- **États** : running animé ; completed vert uniquement sur résultat observé ; failed corail avec erreur réelle visible ; unknown neutre si le résultat manque après arrêt. Un échec d'enfant ne devient pas automatiquement un blocage du run (seul le moteur fait autorité). Ne jamais afficher de fausse réussite ou de statut d'approbation.
- **Relation fiable obligatoire** : les enfants n'apparaissent sous la délégation que si le harnais fournit une identité/corrélation parent-enfant attestable, isolée par run/stage/session/attempt. Un outil de spawn sans corrélation reste une entrée `Delegation · …` dépliable avec ses paramètres/résultats observés, mais sans arborescence inventée. Aucun message libre ne crée de lien.
- **Streaming/focus** : l'appel est mis à jour sur la même clé stable, sans doublon, sans refermer l'élément ni repositionner le focus. Enter et clic déplient/replient, Esc revient à la lecture précédente sans annuler le run ; expansion/scroll manuel suspend le follow. Navigation et commandes LoopForge habituelles conservées.
- **Densité et responsive** : pas de panneau d'inspecteur ; sidebar de supervision inchangée, menu des quatre vues ancré en bas à droite. Vers 60–80 colonnes, masquer la sidebar au profit de la supervision compacte, tronquer le titre et retourner à la ligne les détails ; maintenir commande et actions visibles, y compris à faible hauteur. Glyphes ASCII alternatifs et statut textuel accessibles sans couleur.
- **Provenance et sécurité** : les contenus d'agent sont non fiables, échappés et bornés ; sortie longue inspectable par le mécanisme de détail en lecture seule. N'afficher durée, nombre d'outils, mission ou métriques que si observés. Les vues Focused/All/Raw ne modifient ni la conservation des événements ni leur autorité.

**État existant à réutiliser lors de l'implémentation** : `RunToolEntry` fournit déjà un `Collapsible` et des mises à jour en place ; `adapters/event_store.py` peut enregistrer un `parent_id` natif pour certains événements, mais `cli/run_projection.py` ne construit pas encore un arbre de délégations portable. Avant codage, vérifier les contrats réels des harness et ajouter des tests de corrélation, concurrence, ordre, streaming, panne/unknown, sécurité, redimensionnement (48/52/60/80/100/120/160) et navigation clavier/souris. L’absence de lien fiable doit donner un rendu neutre.

**Handoff** : prochaine étape uniquement sur demande explicite — implémenter ce composant approuvé, tester sur la vraie TUI, committer localement puis demander une acceptation visuelle distincte. Pas de push sans demande explicite.


### 4.6 Suivi du bas, lecture, reprise

Au départ, Live suit la fin du flux. Dès que l'utilisateur :
- remonte manuellement ;
- ouvre un outil, un groupe ou un reasoning ;
- bascule vers une autre vue/étape/tentative ;
- ouvre une sortie plein écran,

le **follow se suspend**. Les nouvelles entrées n'affectent pas la position courante ; indiquer discrètement `↓ N new events · Follow live` si de nouvelles entrées ont été conservées depuis la suspension. Ce contrôle réactive explicitement le follow sur la session **active sélectionnée**. Le compteur ne confond pas les anciennes tentatives avec la session courante.

Aucun scroll forcé au retour d'une vue historique, et focus/état de dépliage préservés durant le streaming. À la réouverture, l'onglet, l'étape, la tentative, la position et le fait d'être en follow sont restaurés. Si le dernier état enregistré était « follow », rejoindre le bas **de la même sélection** ; sinon reprendre la position sauvegardée.

### 4.7 Running, Completed, Blocked et approbations

**Running** : conversation avec outils compacts en mouvement, état principal `Running`, progression de plan facultative ; sidebar non défilante pour le menu en bas.

**Completed (fin d'une exécution, pas nécessairement du run)** : montrer la réponse finale native, puis une carte `Execution result` avec (si connus) artefact, nombre de fichiers réellement modifiés, validation de contrat, état des contrôles et prochaine étape calculée par le moteur. Les liens `View changes` et `View evidences` changent uniquement de vue en préservant étape/tentative. Ne jamais afficher « Verification passed » seulement parce que l'agent le dit. Ne jamais ouvrir une synthèse qui remplace la conversation.

**Blocked** : le flux garde l'erreur et les derniers éléments ; la sidebar montre le blocage ; un bandeau `ACTION REQUIRED` **fixe juste au-dessus de la barre de commandes** présente la description et **les seules actions officiellement disponibles**. La TUI n'invente pas de `Retry` ou `Approve` si le moteur ne les propose pas.

**Waiting for approval** : même emplacement de bandeau, mais libellé `Approval required` (pas `Blocked`) ; lien vers l'artefact et résumé de l'autorité concernés ; la validation passe par les mécanismes existants (confirmation + reçu).

Une erreur récupérable d'outil n'implique pas `run blocked`. L'état `blocked` vient du moteur. Le bandeau d'intervention est prioritaire sans empêcher de consulter Live/Context/Changes/Evidences ni de saisir des commandes admises.

## 5. Spécification de Context

**Objectif** : présenter les instructions **réellement fournies à l'agent** pour l'étape/session sélectionnée, avec une lecture structurée et un accès au raw prompt original.

| Section | Contenu | Ouverture par défaut |
| --- | --- | --- |
| Mission & Role | Tâche, objectif, étape, rôle, harness/adaptateur | Ouverte |
| System Instructions | Instructions du rôle et règles propres à l'étape | Fermée |
| Injected Documents | `task.md`, `loop.md`, `memory.md`, données de pack, sections et références effectivement injectées | Fermée, nombre visible |
| Environment & Git | Workspace, branche, base commit, chemin run, environnement enregistré | Fermée |
| Pack, Skills & Tools | Pack, instructions, compétences et outils réellement déclarés | Fermée |
| Permissions & Security | Droits déclarés **versus** restrictions réellement imposées par le runner/harness | Résumé visible |
| Output Contract | Artefact attendu, format, sections/champs, validations | Résumé visible |
| Validation & Limits | Critères, tentatives, timeout, garde-fous et conditions de passage | Fermée |
| Raw Prompt | **Octets / texte exact enregistré** comme source envoyée ; copie bornée si UI | Fermée |

Aucune autorité n'est accordée au document simplement parce qu'il figure dans le prompt. Exemple : `loop.md` peut déclarer des outils en écriture alors que l'étape Research reste surveillée comme read-only ; afficher `Declared in document` distinct de `Enforced by runner`. Ne **pas** présenter un simple libellé de prompt comme preuve d'une restriction technique.

**Plan de données** : le générateur enregistre en même temps le prompt envoyé et un manifeste versionné de ses sections/source/autorité/hash/références. Interdire de « régénérer » le prompt d'un ancien run en lui attribuant la valeur d'un snapshot exact. Si le manifeste n'existe pas, interprétation de l'ancien Markdown uniquement `derived` ; si le prompt manque, omettre les catégories impossibles ou présenter une information neutre dans la vue demandée, sans bannière globale.

**Sécurité** : chemins confinés sous la racine du run autorisée, aucun chemin arbitraire provenant d'un tool payload ; redaction à l'écran des secrets reconnus, sans affirmer que le prompt sous-jacent a été modifié. Le « raw » sensible demeure local et consultable seulement conformément aux droits du système.

## 6. Spécification de Changes

**Objectif** : montrer les changements **constatés sur le workspace**, distincts des intentions/déclarations de l'agent.

- Affichage initial : **delta de la tentative sélectionnée**.
- Contrôle `Attempt / Run cumulative` : vue du delta de la tentative ou état cumulé de toutes les tentatives de ce run.
- Ligne de synthèse : fichiers ajoutés/modifiés/supprimés/renommés, totaux +/− réellement calculés, base de comparaison exacte.
- Liste de chemins **relatifs**, état Git, éventuellement nombre de lignes et statut binaire.
- `Enter` sur un chemin : aperçu diff lisible, coloré sans dépendre exclusivement de la couleur ; possibilité d'ouvrir en plein écran/pagination.
- Renames, binaires, très grands diffs, fichiers non suivis, worktrees, commits pendant l'exécution : comportements explicites.
- Source de vérité : Git, snapshots de l'agent/runner, patches vérifiés ; **jamais** seulement « Edit file » dans une trace.
- Les fichiers d'artefacts LoopForge (`research.md`, `plan.md`, etc.) sont en **Evidences** ; ils ne deviennent pas automatiquement « fichiers modifiés par l'agent ».
- Dans les étapes read-only : `No workspace changes expected` si aucune modification constatée ; si une modification interdite est détectée, la présenter comme **violation** avec source et raison moteur, sans la masquer.

**Point d'implémentation non résolu par la seule UI** : le diff fiable **par tentative** demande d'enregistrer base/état avant et après l'exécution ou une source de delta existante démontrablement équivalente. Un `git diff` calculé tardivement sur le workspace entier **n'est pas un diff de tentative**. Si le snapshot historique n'existe pas, ne pas attribuer arbitrairement des modifications à la tentative ; seul le cumul fiable peut être présenté.

Aucune action Apply/Discard/Rollback destructive ne fait partie de cette refonte.

## 7. Spécification d'Evidences

**Objectif** : exposer les résultats vérifiables et les approbations sans confondre « l'agent le dit » et « LoopForge le prouve ».

Structure en quatre sections (ordre stable) :

1. **Livrables** — `research.md`, `plan.md`, `implementation-result.json`, `review.md`, `verification.md` ou artefacts spécifiques à l'étape : type, origine, état d'extraction, chemin relatif confiné, hash/date si enregistrés ; lecture seule.
2. **Contrats** — statut du contrat applicable, validateurs responsables, champs/sections manquants, erreurs et référence du document validé.
3. **Tests & vérifications** — pack checks, tests déterministes, patch, diff policy et risk checks ; état `pending/running/passed/failed/blocked/unknown` selon source. Compteurs de tests **seulement** s'ils proviennent d'un résultat structuré/parsable sans ambiguïté.
4. **Décisions humaines** — gate, acteur/statut reçu, artefact/hash approuvé et date si constatée ; refus et historique sans maquiller l'état courant.

**Les cinq niveaux à ne jamais fusionner** :
- `Agent output` : affirmation de l'agent ;
- `Artifact extracted` : donnée persistée ;
- `Contract validated` : validation du contrat LoopForge ;
- `Deterministic verification` : contrôles indépendants ;
- `Human decision` : action explicite d'approbation/refus.

Chaque ligne porte `source / stage / attempt-or-session / outcome` si connus, et un lien vers la preuve. Une vérification ancienne ou pour un ancien candidate revision ne doit pas être affichée comme valable pour la révision courante. Un `adapter.stdout` n'est **pas** un reçu de validation.

## 8. Détails transversaux d'interaction

### 8.1 Navigation clavier — intentions, pas bindings finaux

- `Tab` / `Shift+Tab` : circuler entre sidebar, vue centrale, éléments repliables et barre de commande.
- `↑/↓`, `j/k` si non capturés par un champ : sélectionner/défiler.
- `Enter` : ouvrir un outil/un sous-agent/un reasoning, suivre une étape, activer une vue.
- `Esc` : fermer détail puis revenir à la sélection précédente, sans annuler le run.
- `/` : **barre de commandes LoopForge**, pas recherche textuelle.
- `Ctrl+K` : palette d'actions existante.
- `End` ou raccourci déterminé par revue de collision : `Follow live`.
- Raccourci contextuel à décider par audit des bindings pour : plein écran outil, afficher supervision en mode compact, prochaine/précédente tentative, navigation directe des vues.

Les idées `Alt+1..Alt+4` sont **non validées techniquement** ; ne pas les figer sans vérifier la prise en charge des terminaux. La souris ouvre les mêmes objets et ne doit jamais appeler une action différente. L'aide en bas affiche les commandes effectivement accessibles, selon focus.

### 8.2 Comportement de sélection et persistance

- Préserver la sélection sous `run/stage/attempt-or-session/view` ; ne pas fuiter un outil/une preuve d'une tentative dans une autre.
- Restaurer **onglet/vues, étape, tentative, position et follow** à la réouverture du run ; ce qui n'existe plus retombe proprement sur la dernière sélection valide.
- L'état déplié et le focus doivent survivre au **streaming courant**, sans obligation de tout persister entre redémarrages (choix « reprise intelligente », non « reprise complète »).
- Afficher les nouvelles données seulement si elles appartiennent à la sélection active ; les événements de l'agent courant peuvent continuer à être collectés lorsque l'utilisateur lit une ancienne étape.
- Utiliser des clés stables pour que l'arrivée d'une nouvelle sortie ne remonte pas toute la vue ni ne détruise le focus.

### 8.3 États, absence d'information et accessibilité

L'UI doit distinguer `pending`, `running`, `completed`, `failed`, `blocked`, `cancelled`, `interrupted`, `unknown` lorsque ces états ont un sens. Les couleurs de `DESIGN.md` sont accompagnées de marqueurs textuels et d'icônes ASCII de remplacement. Les messages non fiables s'affichent **littéralement** : aucune interprétation comme Rich markup/commande.

Décision « affichage silencieux » : **ne pas créer de widget « N/A » ou de badge d'observation partielle pour chaque donnée absente**. En revanche, une sortie demandée mais réellement indisponible peut avoir un état vide explicatif dans **la vue concernée** ; un appel `running` sans fin connue reste `unknown` après arrêt. La troncature ne doit pas être dissimulée si l'UI expose une sortie « Raw » ou une sortie complète.

## 9. Audit des sources réelles — dépôt master au 20/10/2026

Cette section distingue **implémenté aujourd'hui** de **proposé**. L'audit est statique à partir des fichiers du dépôt ; aucune session payante/harness live ni campagne de tests ne fait partie de la rédaction documentaire.

### 9.1 Pipeline de données actuellement présent

```text
Harness CLI réel (terminal séparé ou headless)
  ├─ Codex / Claude hooks + transcript natif public lié à une session
  ├─ Kilo / OpenCode plugin message.part.updated (API actuelle du bridge)
  └─ Headless JSONL ou texte lisible selon adapter
        ↓
TerminalObservation / StreamPresenter / adapter_event_lines
        ↓
agent-transcript.log (lisible, borné) / adapter.stdout / spools
        ↓
load_run_agent_snapshot() → RunAgentSnapshot (dernière session)
        ↓
StateStore / UiSnapshot / RunAgentOutput / RunToolEntry
        ↓
RunActivityFeed + RunContextSidebar
```

**Ce qui fonctionne déjà :**
- `RunAgentOutput` et `RunToolEntry` affichent messages, reasoning observable, outils repliables, statuts et Call IDs réutilisés lors des updates.
- Un attempt heading, le prompt, la sortie et le contrat sont chargés via `RunAgentSnapshot`.
- Le moteur fournit l'état du workflow, les blockers, actions, checks et approbations ; les métriques ont un enregistrement dédié ; un index `EvidenceIndex` sait lister/prévisualiser des artefacts.
- Textual conserve déjà une sidebar avec `Live` en bas et deux entrées `Changes` / `Evidences` marquées indisponibles ; cette position est la référence UI souhaitée.
- Le journal issu des hooks et sa présentation incrémentale existent. Le terminal du harness reste actif indépendamment de Live.

**Ce qui n'est pas encore intégré :**
- Vraies vues `Context`, `Changes` et `Evidences` depuis Run ; menu de vues réellement navigable, rendu de chaque vue avec sélection stable.
- Historique consultable **par étape et session**, tentative choisie manuellement : `load_run_agent_snapshot` privilégie le dernier dossier.
- Manifeste structuré et fidèle des sections du prompt ; per-attempt permission evidence claire.
- Modèle d'événements UI versionné persistant, grouping typé, TODO et sous-agents reliés de façon portable.
- Diff Git **par tentative** historisé et cumul correctement identifié.
- Carte finale consolidant uniquement les résultats officiels ; reprise UI persistante de lecture.
- Coût et modèle affichés dans la sidebar Run : `RunSnapshot` expose aujourd'hui essentiellement `total_tokens` et le résumé actuel montre `Status / Progress / Uptime / Tokens`.
- Bandeau de détail plein écran pour outil, modes Focused/All/Raw et navigation des quatre vues.

### 9.2 Inventaire par harness — capacité réellement branchée dans LoopForge

| Harness | Interactive actuellement observé | Headless actuellement exploité | Limites du design à respecter |
| --- | --- | --- | --- |
| **Codex** | Hooks de session/outils + messages/reasoning publics du transcript de la session exacte | `exec --json` ; projection de `agent_message`, `reasoning`, `command_execution`, `file_change`, `mcp_tool_call`, `web_search`, `todo_list`, erreurs et usage quand présents | JSON/transcript natifs évolutifs ; disponibilité du reasoning et des TODO conditionnelle ; hooks peuvent ne pas fournir de sorties intermédiaires. |
| **Claude Code** | Hooks outils + blocs `text`/`thinking` publics du transcript exact | `-p --verbose --output-format stream-json` ; messages, tool_use, tool_result, erreurs | N'afficher que thinking exposé ; pas d'interprétation de signatures/données chiffrées ; le code UI ne transforme pas automatiquement toutes les métadonnées en coûts live. |
| **Kilo Code** | Plugin `message.part.updated` limité à la session capturée | `run --format json --thinking` ; part `text`, `reasoning`, `tool` (état, entrée/sortie/erreur, callID) | N'importe quel événement de plugin n'est pas forcément retenu ; la relation aux sous-agents n'est pas normalisée. |
| **OpenCode** | Bridge plugin similaire à Kilo (interface V1 utilisée par LoopForge) | `run --format json --thinking`, projection correspondante | Changement d'API/version possible ; ne pas supposer V2 supportée. |
| **Aider** | Pas d'adapter interactif documenté par le contrat actuel ; fallback headless | Texte `--no-pretty` | Ne pas typer fictivement messages/outils/reasoning à partir d'un texte arbitraire. |
| **mini-SWE-agent** | Pas de contrat interactif intégré ; fallback headless | Texte sanitaire/borné | Trajectoire native non intégrée en événements fiables. |

Le tableau ci-dessus est un audit **du code LoopForge actuel**, pas une promesse de toutes les possibilités des produits externes. Pour ouvrir plus de champs plus tard, revalider les protocoles installés et tester une fixture native par version pertinente. Voir `docs/decisions/agent-run-observation.md` et `src/loopforge/adapters/local_implementation_adapter.py`.

### 9.3 Contraintes de capture et preuves

- `TerminalObservation` limite le journal et les enregistrements natifs de hook/plugin à environ **131 072 octets** chacun selon chemin ; la lecture du transcript natif est bornée à environ **1 Mio par observation**.
- `load_run_agent_snapshot` lit la **queue** du journal, ou `adapter.stdout` borné en fallback ; ce n'est pas actuellement un historique complet indexé de toutes les sessions.
- `OperationController` limite l'historique d'événements de premier plan à **40** ; ce n'est pas un event store permanent.
- `RunAgentSnapshot` : `attempt_number`, `adapter`, `system_prompt`, `agent_output`, `implementation_contract` et `has_live_transcript`. Le modèle de vue doit être enrichi **sans changer l'autorité**.
- `EvidenceIndex` indexe les fichiers du run et peut donner une prévisualisation bornée ; **il n'attribue pas automatiquement** le niveau de validation officiel à chaque ligne.
- `MetricsService`/`execution.py` peuvent représenter modèle, tokens, coût et durée avec états `reported`/`unavailable`, mais l'écran Run ne les consomme pas tous aujourd'hui.
- `verification.py` écrit preuves de patch, politiques, risques et pack checks ; il faut les lire depuis la source officielle et respecter `candidate_revision` / hashes / reçus de gates.
- Un write déclaré par l'agent n'est pas équivalent à un diff Git ; `workspace_observation.py` fournit des observations Git mais pas, à lui seul, toutes les bases historiques nécessaires à l'écran « tentative ».

### 9.4 Autorité par domaine

| Domaine | Source faisant foi |
| --- | --- |
| Statut et transition du workflow, étapes, blocage, actions autorisées | **Moteur LoopForge** / run state |
| Approbation / refus / hash d'artefact approuvé | **Gates et reçus du moteur** |
| Contrat d'output accepté/rejeté | **Validateur LoopForge** |
| Tests et policy checks | **Vérification déterministe / preuves persistées** |
| Modifications réellement présentes | **Git/workspace snapshots/patches** |
| Messages, tools, reasoning, plan de l'agent | **Événements réellement observés du harness** |
| Prompt envoyé | **Capture immuable du prompt de cette exécution** |
| État visuel et sélection | **StateStore / préférences UI** (jamais autorité workflow) |

## 10. Contrats de données proposés (à implémenter)

### 10.1 Event store normalisé, versionné, append-only par exécution

Il faut **conserver les événements natifs déjà capturés** et produire une projection structurée déterministe, en séparant source brute et présentation. Schéma conceptuel (noms définitifs à valider au codage) :

```json
{
  "schema_version": 1,
  "event_key": "stable-origin-and-sequence",
  "project_id": "project-id",
  "run_id": "run-id",
  "stage_id": "implementation",
  "attempt_id": "attempt-002",
  "session_id": "native-or-run-scoped-session",
  "source": "harness|engine|git|validator",
  "harness": "codex",
  "native_event_id": "optional",
  "native_call_id": "optional",
  "native_parent_id": "optional",
  "order": 42,
  "kind": "tool",
  "status": "running",
  "title": "Shell",
  "preview": "pytest tests/",
  "detail_ref": "relative-safe-artifact-ref",
  "occurred_at": null,
  "observed_at": "2026-10-20T14:00:00Z",
  "capture_state": "complete|partial|bounded",
  "provenance": "native-json|hook|runner"
}
```

Champs réellement absents : **`null` ou omis**, sans valeurs inventées. `occurred_at` ne doit pas être confondu avec l'heure de réception. Les métadonnées de relation et d'identité (Call ID/parent ID) doivent provenir de la source. Les sorties de commande volumineuses sont des **références de détails bornés**, pas des payloads non contrôlés dans `UiSnapshot`.

La projection est idempotente, stable sous redémarrage et indépendante du mode `Focused/All/Raw`. Les anciens `agent-transcript.log` et `adapter.stdout` restent lisibles. Ne pas faire confiance au texte d'un agent pour définir `source=engine`.

### 10.2 Context manifest

```json
{
  "schema_version": 1,
  "run_id": "run-id",
  "stage_id": "research",
  "attempt_id": null,
  "session_id": "stage-session-id",
  "harness": "codex",
  "raw_prompt_ref": "artifacts/stages/research/prompt.md",
  "raw_prompt_sha256": "hash-of-exact-sent-prompt",
  "capture_state": "complete",
  "sections": [
    {
      "id": "mission",
      "source": "task.md",
      "authority": "task-input",
      "summary": "Objective",
      "content_ref": "relative-snapshot-ref"
    }
  ]
}
```

Le manifeste est généré au **même moment** que le prompt. `authority` est la **provenance** de la section, pas une permission accordée à son contenu. Capturer séparément les restrictions effectivement appliquées par le runner si elles sont attestables. Hash/refs relatifs confinés sous la racine autorisée.

### 10.3 Modèle de lecture UI

Étendre `RunSnapshot` par un état de sélection (`stage/session/attempt/view/follow`) et des projections chargées **à la demande** : séquence d'événements paginée, contexte manifest + prompt, métadonnées de diff, index d'evidences, informations sidebar. Les lectures du filesystem se font hors boucle de rendu ; actualiser seulement les objets modifiés et éviter de remonter les widgets Textual existants.

Proposition de stockage du choix UI : clé `project_id/run_id` → `view, stage_id, attempt_id, session_id, scroll_anchor, following`. Ne jamais persister d'autorité moteur dans ces préférences. Définir des migrations/fallback pour anciennes préférences et pour artifacts disparus.

### 10.4 Contraintes de stockage et sûreté

- Périmètre strict par run/stage/session ; aucun rebinding de logs entre projets/attempts.
- Fichiers/chemins via `resolve_artifact` ou garde équivalente ; refuser symlink/junction et traversals hors racine.
- Bornes explicites pour payload, longueur de ligne, vue Markdown, nombre d'événements montés et rendu diff ; pagination/lazy load.
- Les données de l'agent restent **non fiables**, même produites par un CLI local : escaping Rich/Textual, contrôle ANSI, redaction de secrets, lecture sûre.
- Ne pas enregistrer des prompts/sorties sensibles dans des logs globaux supplémentaires.
- Les limites de capture doivent être compatibles avec historique durable ; **ne pas simplement relever sans borne MAX_BYTES**. Définir rotation/segments, indexes et budget de rétention local.

## 11. Maquettes approuvées (schématiques, fictives)

Les maquettes suivantes sont des **états d'un seul layout**, pas des interfaces indépendantes. Elles reflètent la correction D31 : menu des vues **en bas de la sidebar droite**.

### 11.1 Running — flux, outils et sous-agents

```text
┌ LoopForge / MyProject / Run #42 — Auth ─── git:feature/auth  Running ┐
│ Implementation                    [Attempt 02 v] │ CURRENT ACTIVITY │
│                                                  │ Implementation  │
│ Agent                                            │ Codex / 02      │
│ Inspecting authentication flow...                │ Tasks 3/5       │
│   [✓] Read 8 files                         [>]  │ 1 warning       │
│   [✓] 3 searches                           [>]  │                 │
│   [~] Shell · pytest tests/                [>]  │ WORKFLOW        │
│   [>] Reasoning                                 │ ✓ Research      │
│                                                  │ ✓ Planning      │
│ Agent                                            │ > Implementation│
│ Updating token validation...                     │ ○ Verification  │
│   [>] Sub-agent · Code review                    │ ○ Review        │
│                                                  │                 │
│                                                  │ METRICS         │
│                                                  │ 12m / 48k       │
│                                                  ├─────────────────┤
│                                                  │ > Live          │
│                                                  │   Context       │
│                                                  │   Changes       │
│                                                  │   Evidences     │
│ / Enter a LoopForge command...                   └─────────────────┘
└ Tab Navigate   Enter Inspect   Ctrl+K Actions ────────────────────┘
```

### 11.2 Completed — carte terminale

```text
Implementation                   [Attempt 02 v]  | RIGHT SIDEBAR ... |
Agent: Authentication endpoints updated.
  [✓] Shell · pytest tests/                 [>]
  [✓] Agent execution finished

  ┌ Execution result ─────────────────────┐
  │ Agent finished · Contract passed      │
  │ Files changed: 3 (Git proven)         │
  │ Verification: Passed (if validated)   │
  │ Next: Review (from engine)            │
  │ View Changes  |  View Evidences       │
  └───────────────────────────────────────┘

/ Enter a LoopForge command...
```

Le badge global de header reste l'état du **run** ; `Agent finished` dans la carte ne veut pas nécessairement dire `Run complete`.

### 11.3 Blocked — erreur + bandeau fixe

```text
Verification                         [Session v] | RIGHT SIDEBAR... |
  [✓] Patch generated
  [x] Integration tests · Failed      [>]
  ┌ Verification blocked ───────────────────┐
  │ 2 checks failed · View failed checks    │
  └─────────────────────────────────────────┘

┌ ACTION REQUIRED ──────────────────────────────────────────────┐
│ Verification is blocked. Inspect checks before continuing.  │
│ Enter: [action allowed by engine]     Ctrl+K: Other actions  │
└──────────────────────────────────────────────────────────────┘
/ Enter a LoopForge command...
```

Si aucune action moteur n'est disponible, ne pas inventer le bouton ; garder le blocage et les explications.

### 11.4 Compact 60–80 colonnes — sidebar repliée

```text
┌ LoopForge / Run #42                 Running ┐
│ Implementation · Attempt 02  [Supervision] │
│ Codex · 12m · 48k (valeurs connues)        │
│                                         │
│ Agent: Inspecting authentication...     │
│   [✓] Read 8 files                  [>] │
│   [✓] 3 searches                    [>] │
│   [~] Shell · pytest                 [>] │
│                                         │
│ / Enter a LoopForge command...          │
└ Tab  Enter  Esc  Ctrl+K ─────────────────┘

[Supervision] => overlay accessible au clavier :
  Current activity / Problems / Workflow / Metrics
  -----------------------------------------------
  > Live
    Context
    Changes
    Evidences   (menu en bas de l'overlay)
```

## 12. Plan d'implémentation par phases — non exécuté

La séquence suit les dépendances de données **avant** les transformations visuelles, pour éviter une UI séduisante avec des états fabriqués. Chaque phase donne lieu à un commit/test ciblé lors du chantier ultérieur.

### Phase A — Inventaire, fixtures et contrats de preuve

- Figé à une version du repo, auditer les schémas réellement fournis par chaque harness/mode.
- Recenser exactement les chemins `stage/session/attempt`, prompts, sorties, artefacts, métriques, diff bases et gates.
- Constituer fixtures **Codex, Claude, Kilo, OpenCode, Aider, mini-SWE-agent** en modes réellement gérés ; séparément fixtures hooks inter./headless et sortie partielle.
- Spécifier les sources d'autorité, clés stables, limites et modèles `unknown`.

**Acceptation** : chaque champ UI possède une provenance identifiée ; les fixtures ne classent pas de texte arbitraire comme outil ou validation.

### Phase B — Stockage et lecture par stage/session/attempt

- Conserver un historique local durable borné, indexé, idempotent et isolé par identité.
- Ajouter sélection de stage/session/attempt et lecture des anciennes exécutions.
- Ne pas casser le fallback des journaux historiques.
- Ajouter persistance limitée de vue/position/follow.

**Acceptation** : aucune contamination entre runs ; reprise d'une ancienne étape après redémarrage ; pas de perte silencieuse due aux **40** derniers OperationEvents.

### Phase C — Navigation quatre vues et layout

- Sidebar réorganisée : Current Activity → Problems → Workflow → Metrics ; **menu Live/Context/Changes/Evidences fixé en bas à droite**.
- Contrôles actifs ; stage via workflow ; tentative au-dessus du contenu, pas d'onglets horizontaux au-dessus du flux.
- Fallback compact 60/80 colonnes et overlay supervision ; Required Action et commande visibles.
- Navigation keyboard/mouse sans effet moteur ; tests du focus et des collisions de bindings.

**Acceptation** : menu en bas dans Running, Completed et Blocked, même lorsque les métriques sont longues ; aucun clavier capturé par erreur.

### Phase D — Context structuré

- Introduire manifeste + raw prompt exact au point d'injection.
- Sections repliables, provenance, comparaison declared/enforced.
- Fallback best effort des vieux runs **marqué dérivé** ; contrôle des hashes, refs et racines.

**Acceptation** : raw conservé hash-identique à l'entrée réellement envoyée (hors affichage redigé) ; pas de permissions inventées.

### Phase E — Live structuré, groupé et stable

- Projections `Focused/All/Raw` depuis événements conservés, sans filtres de recherche.
- Reasoning fermé, outils mis à jour en place, groupes Read/Search, sous-agents **seulement si corrélés**.
- Détail inline + plein écran, position stable, follow intelligent, badges d'erreurs exacts.
- Carte finale et navigation vers Changes/Evidences sans conclusions inventées.

**Acceptation** : mêmes événements retrouvables dans `All` ; groupement réversible ; call IDs concurrents distincts ; no result → unknown ; scroll manuel non forcé.

### Phase F — Changes et Evidences de confiance

- Diffs per-attempt fondés sur états/snapshots fiables + cumul identifié.
- Comparaison base Git, renames, binaires, arborescence et diff paginé.
- Tableau Evidences lié aux validateurs/checks/gates réels ; valeurs absentes silencieuses.
- Contrôles de `candidate_revision`, sha256, stade/tentative et données obsolètes.

**Acceptation** : aucune modification attribuée faussement à un attempt ; un résultat d'agent ne devient pas un succès déterministe ; preuves périmées identifiées.

### Phase G — Tests UX/E2E, performance et livraison

- Pilotes Textual pour tailles 60/80/120/160, états Running/Completed/Blocked/Approval, clavier/mouse/ASCII, resize et focus.
- Reprise après fermeture, historisation, bornes de logs, erreurs de capture, tests de sécurité sur payloads et chemins.
- Harness fixtures mises à jour selon les versions réellement supportées ; exécuter la suite pertinente, puis la suite complète et consigner les exceptions **réelles** (pas de « PASS » présumé).
- Faire une revue d'acceptation visuelle de chaque maquette avec états de données vides, longues et concomitantes.

**Acceptation finale** : toutes les décisions D01–D31 tenues, aucune mutation moteur implicite, aucun changement de permissions, historique consultable et preuves fiables.

## 13. Matrice de tests d'acceptation

| Scénario | Attendu |
| --- | --- |
| Démarrage sans tentative | État vide pertinent ; pas de faux Attempt 01. |
| Research read-only | Messages/reads visibles ; absence de changes présentée sans activité inventée. |
| Planning en attente d'approbation | Bandeau fixe, approbation via moteur, contexte exact. |
| Implementation avec deux tentatives | Tentative 1 et 2 isolées dans **toutes** les vues ; compteur correct. |
| Agent avec outils simultanés homonymes | Appels séparés par Call ID ; résultats correctement rattachés. |
| Start sans tool result, puis arrêt | `unknown` ; spinner arrêté, pas de réussite inventée. |
| Tools/read/search répétitifs | Groupe compact réversible, erreurs visibles, ordre conservé. |
| Reasoning inexistant / masqué | Pas de bloc fantôme ni de faux avertissement. |
| Délégation avec parent_id | Sous-agent repliable, événements enfants du bon parent. |
| Délégation sans parent_id fiable | Outil/délégation observable, pas de sous-flux fabriqué. |
| Erreur récupérable d'outil | Visible + résumé problèmes ; run pas bloqué si moteur poursuit. |
| Vérification échouée | Échec dans Live, sidebar et Evidences ; gate moteur cohérente. |
| Validation/approval périmées | Ne comptent pas pour le candidat courant. |
| Output du harness signale « passed » | Pas de statut `verified` avant preuve du validateur. |
| Completion agent avant verification | Carte `Agent finished`, verification `pending`, run non marqué terminé. |
| Terminal sans hooks / sans sortie structurée | Flux avec ce qui est observé, aucun diagnostic intrusif de donnée absente. |
| Capture tronquée / journal ancien | Raw décrit la portion disponible, sans « sortie intégrale » mensonger. |
| Mode Focused → All → Raw | Aucun changement des données persistées ni du moteur. |
| Scroll manuel + nouveaux événements | Position et focus stables ; compteur follow incrémenté. |
| Détail plein écran + retour | Reprend au même outil et au même scroll. |
| Changement étape pendant streaming courant | Pas de saut au Live de l'étape active ni de mélange des traces. |
| Quitter puis rouvrir run | Restaure vue/étape/tentative/position/follow selon règle D21. |
| 60, 80, 120, 160 colonnes | Sidebar/menu ou overlay accessible ; commande + action préservées. |
| Hauteur faible | Menu de vues et commande jamais inatteignables. |
| ASCII / terminal sans couleur | Statuts lisibles au texte, pas de dépendance exclusive aux couleurs. |
| Payload malformé/ANSI/chemin externe | Aucun markup, débordement ou lecture hors racine. |
| Accès à Changes d'une vieille tentative sans snapshot | Aucun delta faussement attribué, cumul restant éventuellement disponible. |
| Navigation quatre vues | **En bas à droite** sur large, **en bas de supervision compacte** sur étroit, aucun onglet horizontal concurrent. |

## 14. Fichiers candidats et frontières de changement

| Zone | Responsabilité future |
| --- | --- |
| `src/loopforge/cli/textual_app/widgets.py` | Widgets Run, sidebar à menu bas, sections Live, disclosure, détail. |
| `src/loopforge/cli/textual_app/app.py` | Bindings, layout responsive, navigation, chargement sélectif, follow. |
| `src/loopforge/cli/textual_app/run_presenter.py` | Projections lisibles et regroupements déterministes, états visuels. |
| `src/loopforge/cli/textual_app/styles.tcss` | Densité, panneaux, menu de vues, fallback étroit et couleurs de `DESIGN.md`. |
| `src/loopforge/cli/models.py`, `state_store.py` | Snapshots typés, sélection et publication d'état UI ; aucune autorité workflow. |
| `src/loopforge/cli/run_artifacts.py` | Lecture par stage/session/attempt et compatibilité avec les anciens journaux. |
| `src/loopforge/adapters/observation.py`, `observation_hook.py`, `local_implementation_adapter.py` | Captures et projections des événements effectivement observés, IDs, limites. |
| `src/loopforge/adapters/commands.py` | Conserver l'exécution terminal-native et les conventions par harness. |
| `src/loopforge/engine/workspace_observation.py`, `verification.py` | Origine des états/diffs et résultats déterministes. |
| `src/loopforge/cli/evidence.py` | Index des artefacts et lecture sûre de preuves. |
| `src/loopforge/engine/metrics.py`, `execution.py` | Mesures/reporting, distinguer signal disponible et absence. |
| `tests/test_run_transcript_ui.py`, `tests/test_cli_textual_app.py`, tests d'intégration | Caractérisation, streaming, reprise, tailles, gates, indépendance moteur. |

**Conserver** les frontières de validation, les reçus d'approbation, les mécanismes de confinement, les formats existants et la séparation terminal/observateur. Les détails de schéma exacts doivent être vérifiés contre les tests du moteur **avant** l'implémentation.

## 15. Hors périmètre, dépendances et questions de réalisation

**Hors périmètre validé :** recherche textuelle et filtres avancés ; panel d'inspecteur permanent ; PTY intégré ; orchestration/sous-agent additionnel créé pour la présentation ; synthèse IA nouvelle ; changement de permissions et d'autonomie ; outils destructifs Git ; nouveaux connecteurs distants ; refonte de Home/Projects ; éditeur d'artefact depuis Evidences.

**Dépendances techniques à résoudre sans nouvelle interview produit :**
- Choisir la granularité durable de l'event store et sa politique de rétention bornée.
- Définir un schéma de lien stage → session → attempt pour les étapes non-implémentation.
- Prouver la disponibilité de base/snapshot pour tout diff historique par tentative.
- Fixer les seuils responsive par tests plutôt qu'arbitrairement.
- Auditer les shortcuts Textual existants avant d'ajouter plein écran / switch rapide.
- Déterminer si une version de harness expose réellement sous-agents, TODO ou usage et tester son contrat.
- Définir redaction et sauvegarde du raw prompt sans divulgation de secrets.
- Préciser les états de focus/menu quand un champ de commande est actif.

Ces points sont des **décisions d'ingénierie** ; ils ne remettent pas en cause D01–D31. Si une capacité souhaitée n'est pas observable, livrer un état neutre plutôt qu'une simulation.

## 16. Critère de clôture de la refonte

Une personne doit pouvoir : ouvrir un run, comprendre instantanément l'activité, naviguer dans son historique, consulter une tentative antérieure sans mélange, déplier un outil ou sous-agent observable, voir les modifications Git avérées, retrouver les preuves officielles, agir sur une approval réelle, puis rouvrir le run et retrouver sa lecture. Le menu des vues reste **en bas à droite comme dans l'UI actuelle**, les métriques sont essentielles, le terminal de l'agent est indépendant et aucune information absente n'est présentée comme une vérité.

**Ce document est uniquement une spécification approuvée. Aucun composant décrit comme « futur » n'est considéré implémenté ou testé par la rédaction de cette page.**
