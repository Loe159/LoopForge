---
title: "Run TUI — amélioration visuelle composant par composant"
type: ux-visual-refinement-plan
date: 2026-10-20
status: plan-approved
implementation: components-9-to-14-implemented-tested-local
parent_plan: 2026-10-20-001-run-live-context-ux-plan.md
---

# LoopForge — plan de finition visuelle du Run TUI

## 1. Intention et source de vérité

Retrouver une TUI dense, agréable à lire et immédiatement compréhensible, **sans la transformer en site web**. La capture du Run / Live du 20 octobre montre notamment un grand outil Shell déplié dont le texte et le JSON ressemblent à un journal brut. L'interface doit guider la lecture par la typographie de terminal, les espacements, les fonds, les couleurs sémantiques et les disclosures, pas par une accumulation de cartes.

Ce plan **complète**, sans remplacer, les décisions D01–D31 de `2026-10-20-001-run-live-context-ux-plan.md`. Les règles de `DESIGN.md` restent la source de vérité : fond graphite à nuance violette, lavande réservée au focus, vert menthe pour la réussite, corail pour l'échec, ambre pour l'attention ; police monospace du terminal, cadres carrés et absence d'ombres/dégradés. Le comportement moteur, les actions, les permissions et les quatre vues ne changent pas.

**Mode de travail actualisé par l'utilisateur le 21/10/2026 : maquettes groupées, validation à la fin.** Les composants 1 à 7 restent validés et le composant 8 est conservé en l'état. Préparer des variations supplémentaires d'Execution Result et les maquettes des composants 10 à 14, sans arrêt de validation entre ces propositions. La revue utilisateur porte sur l'ensemble du dossier avant l'implémentation. Une approbation du plan n'approuve **pas** automatiquement les maquettes.

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
| 8 | **Erreur, warning, tool unknown — conservé en l'état** | Aucune refonte ni interaction supplémentaire, décision UX du 21/10/2026 dans le plan parent §4.2 | Garanties existantes préservées ; passer au composant 9 |
| 9 | **Execution Result** | Synthèse de fin d'exécution, actions View Changes/Evidences | Agent terminé ≠ run terminé/verified |
| 10 | **Context — documents** | Sections, provenance, sections Markdown sûres, raw prompt distinct | Prompt exact accessible ; declared ≠ enforced |
| 11 | **Evidences — preuves** | Livrables, contrats, checks, décisions lisibles, confiance explicite | Artéfact, validation, vérification et approbation non confondus |
| 12 | **Supervision / workflow / métriques** | Hiérarchie de la sidebar, focus étape active vs étape consultée, densité | Menu quatre vues fixé en bas à droite ; informations non disponibles omises |
| 13 | **Command bar / navigation** | Champ, modes Focused/All/Raw, session selector, shortcuts, action required | Keyboard-first, menu fixe, action réelle visible, pas de perte d'espace |
| 14 | **Recette visuelle intégrée** | Captures du cockpit complet et états Running/Completed/Blocked/Approval | Cohérence de tous les composants, sans refonte fonctionnelle additionnelle |

L'ordre des lots 1 et 2 privilégie le problème principal visible sur la capture : **Tool Call** et **Agent Message**. Les lots 3 et 4 sont séparés volontairement pour ne pas confondre changement annoncé et changement prouvé.

## 5. Protocole de validation de chaque composant

1. **Maquettes préalables** : deux variantes terminal-native, une à largeur confortable (~120 colonnes), une compacte (~80) pour l'option recommandée ; exemples basés sur contenu réaliste mais explicitement fictif. Inclure état replié, déplié, running, completed, failed/unknown et contenu long lorsque pertinent.
2. **Choix utilisateur groupé (instruction du 21/10/2026)** : terminer les maquettes et variations des lots 9 à 14, puis recueillir la validation d'ensemble. Ne pas interrompre le maquettage entre composants ; ne pas commencer le code produit avant cette validation.
3. **Implémentation bornée** : modifier prioritairement `textual_app/widgets.py`, `run_presenter.py`, `styles.tcss` ; `app.py` seulement pour l'intégration UI indispensable. Réutiliser les contrats et abstractions existants.
4. **Preuve** : tests unitaires de rendu, pilot Textual et captures réelles largeur 60/80/120/160, clavier/ASCII/streaming/payload malformé ; vérifier régressions liées. Limiter les inspections de finition à une passe groupée, corrections groupées, confirmation finale.
5. **Validation de l'implémentation** : montrer les captures réelles et les résultats factuels après implémentation des choix retenus ; la validation groupée des maquettes ne vaut pas preuve runtime. Pas de push automatique.

Un état de suivi par lot peut évoluer `à maquetter → maquette soumise → maquette approuvée → implémenté → testé → validé`. L'acceptation du présent plan ne déclenche aucune implémentation.

## 6. Premier lot à présenter : Tool Call

**But :** remplacer la vue de la capture (Shell ouvert contenant commande et gigantesque JSON indifférenciés) par une entrée condensée et inspectable.

La future proposition comparera deux représentations : (A) **ligne technique très sobre** avec contenu déplié sur fond atténué ; (B) **mini-entête d'opération** avec commande courte et statut séparé. Dans les deux cas, la sortie longue doit être identifiable et manipulable sans écraser le reste de Live. L'état in_progress, la fin réussie, l'échec, l'absence de résultat et les appels simultanés doivent être illustrés.

**À arbitrer avec l'utilisateur pendant la maquette :** densité d'une entrée fermée, placement du nom d'outil et de la commande, aperçu de sortie quand replié, apparence de l'ouverture et action plein écran. Ne pas figer ces microdécisions avant validation.

## 7. Hors périmètre

Aucun changement d'orchestration, de workflow, de permission, de prise d'autorité, de persistence de preuve ni d'adapter sans nécessité démontrée. Aucun PTY intégré, recherche/filtres avancés, nouveau framework de widgets, nouvelle UI web, nouvelle palette ou refonte Home. Aucune conversion du Raw en conversation rendue.

## 8. État du chantier

**Plan validé.** Composant 1 (Tool Call) : variante **hybride validée** (ligne compacte à la Codex, détails structurés) ; supprimer de la surface Live « Recorded tool response », les raccourcis contextuels redondants et le Call ID visible. Implémentation locale effectuée, **validée visuellement par l’utilisateur** après ajustement variante A (suppression du cadre extérieur « Agent Output », conservation des rails discrets). Composant 2 (Agent Message) : maquette A validée, Markdown Rich non cliquable, blocs de code colorés, listes et citations sobres, streaming partiel testé ; implémentation locale et tests effectués, **validée visuellement par l’utilisateur** après amélioration du contraste du code inline et des citations. Composant 3 (File Changed) : affichage groupé inspiré Codex/OpenCode validé, sans M/A/D, chemins natifs déclarés, compteurs uniquement depuis captures de session complètes, diff inline repliable par fichier avec numérotation sur une seule colonne, coloration syntaxique, trois lignes de contexte et sans bouton Changes ; implémenté, testé et **validé visuellement par l’utilisateur** après correction du contraste des lignes Markdown supprimées. Composant 4 (File Diff — vue Changes) : **variante B approuvée**, explorateur de fichiers à gauche et aperçu de diff à droite ; reprise du rendu syntaxique Kilo (une colonne de numéros, trois lignes de contexte retenues, ajouts/suppressions contrastés), conservation de la sélection, navigation clavier, basculement Attempt / Run cumulative, dispositions verticale étroite, états binaire/renommage/tronqué/périmé/indisponible. Implémentation locale effectuée, **validée visuellement par l’utilisateur** après les retouches de l’explorateur : dossiers interactifs et repliables au clic/Entrée/flèches, ↑/↓ naviguent dans l’arbre, → ouvre un dossier ou accède à son premier enfant, ← ferme un dossier ou remonte depuis un fichier au dossier parent, état et focus conservés pendant les rafraîchissements, navigation en deux panneaux dès 52 colonnes (arbre à gauche, diff à droite, y compris aux largeurs 60–119), bascule arbre/diff réservée aux terminaux de moins de 52 colonnes **lorsque la hauteur manque** ; à moins de 52 colonnes mais dès 14 lignes utiles pour le corps Changes, arbre défilable en haut et diff défilable en bas, tous deux visibles ; transition responsive préservant sélection et navigation clavier, boutons Attempt / Run cumulative espacés du contenu et toujours alignés. Composant 5 (Reasoning) : **variante A approuvée le 21 octobre 2026**, avec suppression de toute ligne `Source: ...`. Affichage discret dans Live, replié par défaut ; dépliage clavier/souris, détail littéral, suivi du bas suspendu à l'ouverture, identité/focus préservés lors du streaming, aucune donnée de reasoning reconstituée. Implémentation et tests locaux effectués, **validée visuellement par l’utilisateur le 21 octobre 2026**. Démonstration : `PYTHONPATH=src .venv/bin/python tools/demo_reasoning.py`. Composant 6 (Plan / TODO agent) : **variante B approuvée avec TODO imbriqués dans la sidebar Workflow**, implémentation locale testée le 21 octobre (Textual, clavier, souris, responsive). Démo : `PYTHONPATH=src .venv/bin/python tools/demo_plan_todo.py`. **Composant 6 validé visuellement par l’utilisateur le 21 octobre 2026. Aucun push.**

**Composant 7 (Sous-agent / Délégation) : variante A « Flux compact » implémentée et validée visuellement par l'utilisateur le 21 octobre 2026**, après deux retours successifs sur le contraste du focus. Le rendu actualise réellement les styles du `CollapsibleTitle`, y compris sur la délégation non corrélée `Delegation · spawn_agent` (statut `Unknown`), au dépliage, pendant le streaming et lorsque le focus change. La hiérarchie enfant est affichée exclusivement quand les identifiants natifs permettent la corrélation ; une délégation non corrélée conserve une simple entrée repliable. Tests dédiés et de régression exécutés ; commit correctif final `90598ff`. Démonstration : `PYTHONPATH=src .venv/bin/python tools/demo_sub_agent.py`. **Aucun push demandé.**

**Composant 8 (Erreur, warning, tool unknown) : conservé en l'état.** La décision UX du 21/10/2026, consignée dans le plan parent §4.2 et le commit `03034b7`, exclut explicitement sa refonte. Les maquettes proposées par erreur ensuite sont retirées, sans implémentation ; aucune validation supplémentaire n'est attendue pour ce composant.

**Composants 9 à 14 : maquettes terminées, soumises à la revue groupée demandée par l'utilisateur le 21/10/2026.** [Galerie locale](../previews/live-review-09-14/index.html) et [dossier de conception](../previews/live-review-09-14/README.md). 31 maquettes statiques PNG/SVG/texte, toutes à données fictives ; aucune implémentation produit, aucune variante approuvée.

- **9 — Execution Result** : A/B précédentes conservées, nouvelles variantes C « Deux filets », D « Résumé dépliable », E « Suite en premier » ; C et D à 80 colonnes. Réponse native avant reçu, faits conditionnels, liens Changes/Evidences sans exécution moteur.
- **10 — Context** : A « Sections de lecture », B « Sommaire et document » ; A à 80 colonnes, états Raw borné, redaction, ancien prompt dérivé et capture absente. Droits déclarés distincts des mécanismes runner enregistrés.
- **11 — Evidences** : A « Registre par niveau », B « Liste et reçu » ; A à 80 colonnes, reçu courant/périmé, approbation humaine, absence de preuve et contrat explicite.
- **12 — Supervision / Workflow / métriques** : A « Panneaux structurés », B « Titres sobres » ; lecture historique distincte de l'étape active, TODO imbriqués inchangés, overlay 80 colonnes, focus et métriques optionnelles.
- **13 — Commande / navigation** : A « Dock encadré », B « Dock réduit » ; B à 80 colonnes, modes de lecture, suivi suspendu, Raw borné, texte sans slash inerte, blocage sans action primaire. Bindings existants uniquement.
- **14 — Cockpit intégré** : assemblage proposé 9C/10A/11A/12B/13B ; Running 120/160, fin d'exécution 120, Blocked 120, Approval 120/80, ASCII 60×24 et Running 120×24. **Maquettes d'ensemble uniquement : recette runtime à réaliser après implémentation.**

Les choix se font en fin de revue, sans nouvel arrêt entre ces composants. Les champs de la galerie ne transmettent rien et ne valent pas une approbation moteur. Aucun push demandé.

### Retour utilisateur sur la revue groupée — 21/10/2026

Choix reçus : **9A, 10B, 11B, 12A, 13A et composition intégrée**. Ajustements : Execution Result sans les boutons de navigation, priorité au déclenchement de l'étape suivante ; titres des panneaux de supervision en capitales ; `Approval required` orange et Command Input actuel conservé. La recommandation initiale 9C/10A/11A/12B/13B est remplacée par ces préférences.

[Décisions détaillées](2026-10-21-004-live-selected-composition.md) et [composition ajustée](../previews/live-review-09-14/revision-01/index.html). L'action Next step persistante au-dessus de la commande est proposée pour répondre à la priorité exprimée. Le retour précise qu'il **ne déclenche aucune implémentation ni approbation moteur** : seuls documents et maquettes sont actualisés, sans code produit.

### Autorisation et implémentation locale — 21/10/2026

L'utilisateur a ensuite validé la composition ajustée et demandé son implémentation. Les lots 9 à 14 sont implémentés localement : reçu A sans boutons, Context B et Evidences B dans un navigateur partagé, panneaux de supervision à titres en capitales, `Approval required` orange, action Next step via le dispatch existant et Command Input conservé. Le sélecteur est compact à faible hauteur ; le menu des vues reste fixé au bas de la supervision. Le composant 8 n'est pas redessiné.

[Captures Textual réelles et résultats des contrôles](../previews/live-selected-implementation/README.md). Les données de démonstration sont fictives ; la validation des maquettes n'est pas une approbation moteur ni une publication. Les limites éventuelles de la suite complète sont documentées dans le rapport, sans affirmer un succès global absent.
