---
title: "Run TUI — amélioration visuelle composant par composant"
type: ux-visual-refinement-plan
date: 2026-10-20
status: plan-approved
implementation: components-1-to-3-validated-component-4-implemented-awaiting-review
parent_plan: 2026-10-20-001-run-live-context-ux-plan.md
---

# LoopForge — plan de finition visuelle du Run TUI

## 1. Intention et source de vérité

Retrouver une TUI dense, agréable à lire et immédiatement compréhensible, **sans la transformer en site web**. La capture du Run / Live du 20 octobre montre notamment un grand outil Shell déplié dont le texte et le JSON ressemblent à un journal brut. L'interface doit guider la lecture par la typographie de terminal, les espacements, les fonds, les couleurs sémantiques et les disclosures, pas par une accumulation de cartes.

Ce plan **complète**, sans remplacer, les décisions D01–D31 de `2026-10-20-001-run-live-context-ux-plan.md`. Les règles de `DESIGN.md` restent la source de vérité : fond graphite à nuance violette, lavande réservée au focus, vert menthe pour la réussite, corail pour l'échec, ambre pour l'attention ; police monospace du terminal, cadres carrés et absence d'ombres/dégradés. Le comportement moteur, les actions, les permissions et les quatre vues ne changent pas.

**Mode de travail : un composant à la fois.** Aucun changement dans le code de l'interface avant validation du composant correspondant. Chaque composant passe par proposition de maquettes → avis utilisateur → ajustement éventuel → implémentation isolée → capture réelle + tests → validation utilisateur → composant suivant. Une approbation du plan n'approuve **pas** automatiquement les maquettes de chaque composant.

## 2. Problèmes constatés dans le code et sur la capture

1. `agent_body_renderable` (`textual_app/run_presenter.py`) conserve volontairement la prose Markdown comme `Text` brut ; seuls les *fenced code blocks* sont analysés avec `Rich.Syntax`. Titres, listes et emphases des messages ne sont donc pas rendus.
2. `_tool_output_text` tente une coloration limitée aux commandes `$ …` et JSON précédé de quelques labels. Un dump Shell comportant `Tool call (…) / Output / { … }` peut échapper à cette détection. Les sorties typées devraient suivre le contrat des événements, pas être classées selon des mots libres.
3. `RunToolEntry` (`textual_app/widgets.py`) replie/déplie une zone de détails entière ; une sortie très longue prend l'essentiel de la page et dilue le commandement et le résultat.
4. `RunDetailEntry` présente Context / Changes / Evidences avec du `Static(Text(body))` : pas de présentation Markdown ou de diff coloré.
5. `styles.tcss` et les widgets contiennent des valeurs visuelles répétées. Il faut améliorer la hiérarchie sans rompre la palette existante ni rendre toutes les entrées colorées.
6. L'état courant, l'historique sélectionné, les modes de lecture et les panneaux latéraux sont fonctionnels mais manquent de contraste hiérarchique dans la capture.

Ces observations ne démontrent pas de défaut du moteur. Le texte d'un agent reste une **déclaration** ; seuls moteur, validateur et snapshots attestés créent des statuts officiels.

## 3. Contrat de rendu transverse

- **Prose de l'agent :** rendu Markdown sûr (titres, listes, citations, emphases, inline code, liens, fenced code), mais jamais interprétation de markup Rich, ANSI ou liens exécutables arbitraires. Préserver les contenus littéraux et les réponses partielles en streaming.
- **Code :** `Rich.Syntax` pour langage explicite (bash, JSON, Python, diff, etc.), thème compatible avec la palette de `DESIGN.md`. Fallback texte neutre si langage ou structure inconnus. Éviter de prétendre qu'une sortie arbitraire est du JSON ou du code.
- **Raw :** conserver le journal littéral, sa provenance et les bornes de capture ; aucun « embellissement » qui modifierait ou masquerait la structure du journal.
- **État :** succès/échec/en cours/inconnu indiqués par **mot + marqueur + accent sémantique** ; aucune réussite déduite d'une couleur, d'un exit code absent ou d'un simple message agent.
- **Densité :** un message agent = unité de lecture avec respiration ; un tool call replié = une ou deux lignes ; détails plus profonds à la demande. Le feed ne doit pas devenir une pile de cartes et de bordures.
- **Robustesse :** 60/80/120/160 colonnes, faibles hauteurs, ASCII, commandes longues, chemins Unicode, erreurs, sorties très longues, stream partiel. Préserver le suivi intelligent, l'ordre, les Call IDs, le focus et la sélection.
- **Sécurité :** sanitation/redaction existantes, textes/chemins non fiables, aucune sortie de la racine du run, aucune régression d'ACL ou de validation.

## 4. Séquence de livraison et points d'arrêt

| Lot | Composant | Proposition à examiner | Acceptation spécifique |
| --- | --- | --- | --- |
| 0 | Fondation visuelle / règle de rendu | Échelle de texte terminal, contrastes, fonds, marqueurs, rendu de code et Markdown ; mini-samples dark/ASCII | Système cohérent avec DESIGN.md, sans modifier l'écran Home |
| 1 | **Tool Call** (Shell, MCP, Read, Search) | Ligne résumée + états, arguments/source/sorties repliables, rendu syntaxique, sortie longue plein écran | Call IDs concurrents distincts, état mis à jour en place, erreurs visibles, détail fermé par défaut, commandes compréhensibles |
| 2 | **Agent Message** | Mise en page Markdown sobre, code fenced coloré, emphases et listes | Texte d'origine préservé, streaming stable, markup hostile inerte |
| 3 | **File Changed — événement Live** | Ligne compacte : chemin, action déclarée, provenance, lien Changes | Une annonce du harness ne prend jamais le statut « Git vérifié » |
| 4 | **File Diff — vue Changes** | A/M/D/R, compteurs attestés, diff +/− contrasté, binaire/rename/tronqué | Base/attempt exacts, absence de comparaison fiable non simulée |
| 5 | **Reasoning** | Ligne très discrète, repliée, détails lisibles sur demande | Jamais de thinking non exposé ; rendu sans envahir le feed |
| 6 | **Plan / TODO agent** | Étapes compactes, états fournis ; résumé optionnel dans l'activité | Progression agent distincte de celle du moteur |
| 7 | **Sous-agent / délégation** | Nœud repliable, rôle et activité enfant lorsqu'ils sont réellement reliés | Aucun parent/enfant inféré depuis du texte libre |
| 8 | **Erreur, warning, tool unknown** | Signal d'alerte immédiatement scannable, détail et reprise possibles | Échec récupérable ≠ run bloqué ; absence de résultat ≠ succès |
| 9 | **Execution Result** | Synthèse de fin d'exécution, actions View Changes/Evidences | Agent terminé ≠ run terminé/verified |
| 10 | **Context — documents** | Sections, provenance, sections Markdown sûres, raw prompt distinct | Prompt exact accessible ; declared ≠ enforced |
| 11 | **Evidences — preuves** | Livrables, contrats, checks, décisions lisibles, confiance explicite | Artéfact, validation, vérification et approbation non confondus |
| 12 | **Supervision / workflow / métriques** | Hiérarchie de la sidebar, focus étape active vs étape consultée, densité | Menu quatre vues fixé en bas à droite ; informations non disponibles omises |
| 13 | **Command bar / navigation** | Champ, modes Focused/All/Raw, session selector, shortcuts, action required | Keyboard-first, menu fixe, action réelle visible, pas de perte d'espace |
| 14 | **Recette visuelle intégrée** | Captures du cockpit complet et états Running/Completed/Blocked/Approval | Cohérence de tous les composants, sans refonte fonctionnelle additionnelle |

L'ordre des lots 1 et 2 privilégie le problème principal visible sur la capture : **Tool Call** et **Agent Message**. Les lots 3 et 4 sont séparés volontairement pour ne pas confondre changement annoncé et changement prouvé.

## 5. Protocole de validation de chaque composant

1. **Maquettes préalables** : deux variantes terminal-native, une à largeur confortable (~120 colonnes), une compacte (~80) pour l'option recommandée ; exemples basés sur contenu réaliste mais explicitement fictif. Inclure état replié, déplié, running, completed, failed/unknown et contenu long lorsque pertinent.
2. **Choix utilisateur** : validation ou commentaires ; **stop tant que ce composant n'est pas validé**.
3. **Implémentation bornée** : modifier prioritairement `textual_app/widgets.py`, `run_presenter.py`, `styles.tcss` ; `app.py` seulement pour l'intégration UI indispensable. Réutiliser les contrats et abstractions existants.
4. **Preuve** : tests unitaires de rendu, pilot Textual et captures réelles largeur 60/80/120/160, clavier/ASCII/streaming/payload malformé ; vérifier régressions liées. Limiter les inspections de finition à une passe groupée, corrections groupées, confirmation finale.
5. **Nouvelle validation** : montrer la capture et les résultats factuels ; considérer le lot terminé uniquement après retour explicite de l'utilisateur. Pas de push automatique.

Un état de suivi par lot peut évoluer `à maquetter → maquette soumise → maquette approuvée → implémenté → testé → validé`. L'acceptation du présent plan ne déclenche aucune implémentation.

## 6. Premier lot à présenter : Tool Call

**But :** remplacer la vue de la capture (Shell ouvert contenant commande et gigantesque JSON indifférenciés) par une entrée condensée et inspectable.

La future proposition comparera deux représentations : (A) **ligne technique très sobre** avec contenu déplié sur fond atténué ; (B) **mini-entête d'opération** avec commande courte et statut séparé. Dans les deux cas, la sortie longue doit être identifiable et manipulable sans écraser le reste de Live. L'état in_progress, la fin réussie, l'échec, l'absence de résultat et les appels simultanés doivent être illustrés.

**À arbitrer avec l'utilisateur pendant la maquette :** densité d'une entrée fermée, placement du nom d'outil et de la commande, aperçu de sortie quand replié, apparence de l'ouverture et action plein écran. Ne pas figer ces microdécisions avant validation.

## 7. Hors périmètre

Aucun changement d'orchestration, de workflow, de permission, de prise d'autorité, de persistence de preuve ni d'adapter sans nécessité démontrée. Aucun PTY intégré, recherche/filtres avancés, nouveau framework de widgets, nouvelle UI web, nouvelle palette ou refonte Home. Aucune conversion du Raw en conversation rendue.

## 8. État du chantier

**Plan validé.** Composant 1 (Tool Call) : variante **hybride validée** (ligne compacte à la Codex, détails structurés) ; supprimer de la surface Live « Recorded tool response », les raccourcis contextuels redondants et le Call ID visible. Implémentation locale effectuée, **validée visuellement par l’utilisateur** après ajustement variante A (suppression du cadre extérieur « Agent Output », conservation des rails discrets). Composant 2 (Agent Message) : maquette A validée, Markdown Rich non cliquable, blocs de code colorés, listes et citations sobres, streaming partiel testé ; implémentation locale et tests effectués, **validée visuellement par l’utilisateur** après amélioration du contraste du code inline et des citations. Composant 3 (File Changed) : affichage groupé inspiré Codex/OpenCode validé, sans M/A/D, chemins natifs déclarés, compteurs uniquement depuis captures de session complètes, diff inline repliable par fichier avec numérotation sur une seule colonne, coloration syntaxique, trois lignes de contexte et sans bouton Changes ; implémenté, testé et **validé visuellement par l’utilisateur** après correction du contraste des lignes Markdown supprimées. Composant 4 (File Diff — vue Changes) : **variante B approuvée**, explorateur de fichiers à gauche et aperçu de diff à droite ; reprise du rendu syntaxique Kilo (une colonne de numéros, trois lignes de contexte retenues, ajouts/suppressions contrastés), conservation de la sélection, navigation clavier, basculement Attempt / Run cumulative, dispositions verticale étroite, états binaire/renommage/tronqué/périmé/indisponible. Implémentation locale effectuée, **en attente de validation visuelle finale** (retouches de l’explorateur : dossiers interactifs et repliables au clic/Entrée/flèches, ↑/↓ naviguent dans l’arbre, → ouvre un dossier ou accède à son premier enfant, ← ferme un dossier ou remonte depuis un fichier au dossier parent, état et focus conservés pendant les rafraîchissements, navigation en deux panneaux dès 52 colonnes (arbre à gauche, diff à droite, y compris aux largeurs 60–119), bascule arbre/diff réservée aux terminaux de moins de 52 colonnes **lorsque la hauteur manque** ; à moins de 52 colonnes mais dès 14 lignes utiles pour le corps Changes, arbre défilable en haut et diff défilable en bas, tous deux visibles ; transition responsive préservant sélection et navigation clavier, boutons Attempt / Run cumulative espacés du contenu et toujours alignés). Aucun autre composant approuvé pour implémentation.
