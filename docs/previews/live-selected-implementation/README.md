# Live — implémentation locale de la composition validée

Composition **9A / 10B / 11B / 12A / 13A**, autorisée après validation des
maquettes ajustées. Les composants 1 à 7 sont conservés et le composant 8
Error / Warning / Unknown n'est pas redessiné.

[Inspection Impeccable et revue de code](REVIEW.md) : défaut de routage
d'Entrée sur les boutons du run reproduit, corrigé et couvert par un test.

## Captures réelles

Ces images proviennent du rendu **Textual de l'application modifiée**, avec des
fixtures synthétiques. Elles ne proviennent pas du générateur de maquettes et
ne sont pas une preuve d'exécution d'un harness réel.

| Vue / état | Capture |
| --- | --- |
| Live, fin d'exécution et prochaine action, 120 × 40 | [PNG](live-ready-120x40.png) · [SVG](live-ready-120x40.svg) |
| Approval et commande, 80 × 24 | [PNG](live-approval-80x24.png) · [SVG](live-approval-80x24.svg) |
| Next step et commande, 60 × 24 | [PNG](live-ready-60x24.png) · [SVG](live-ready-60x24.svg) |
| Live en cours, 160 × 40 | [PNG](live-running-160x40.png) · [SVG](live-running-160x40.svg) |
| Context B, 120 × 36 | [PNG](context-ready-120x36.png) · [SVG](context-ready-120x36.svg) |
| Evidences B, 120 × 36 | [PNG](evidences-ready-120x36.png) · [SVG](evidences-ready-120x36.svg) |

La capture désactive uniquement `NO_COLOR` pour présenter la palette ; le produit
continue à respecter cette variable. Les coordonnées du rendu Textual sont
conservées dans les SVG ; leurs références de polices distantes sont retirées
pour garder des fichiers consultables localement sans requête externe.

Démo interactive, sans exécution moteur ni écriture d'un run :

```sh
PYTHONPATH=src .venv/bin/python tools/demo_live_composition.py
PYTHONPATH=src .venv/bin/python tools/demo_live_composition.py --view Context
PYTHONPATH=src .venv/bin/python tools/demo_live_composition.py --view Evidences
PYTHONPATH=src .venv/bin/python tools/demo_live_composition.py --state approval
```

Dans cette fixture, Ctrl+Enter ouvre une explication ; aucune opération réelle
n'est exécutée. Dans le produit, ce raccourci conserve le dispatch moteur et les
confirmations existantes.

## Changements livrés

- Reçu A informatif, sans boutons de navigation. Les faits proviennent des
  snapshots conservés : statut d'exécution, référence d'artefact, comparaison
  fiable et vérification du candidat correspondant, lorsqu'ils sont disponibles.
  Une simple clôture reste neutre ; aucune réussite n'est inférée.
- Bandeau Next step également visible à l'état Ready, via `ActionDescriptor` et
  `request_action`. Action absente ou indisponible, exécution active, actualisation
  post-opération ou fenêtre modale : pas de nouveau déclenchement.
- Context et Evidences partagent le navigateur liste/détail. Sélection, focus et
  widgets sont conservés lors des actualisations du même périmètre ; une autre
  session/run ne garde pas le contenu précédent. Markdown sûr dans Context,
  Raw littéral, métadonnées de preuve littérales et JSON/diff colorés selon leur
  type déclaré. Open artifact/F4 ouvre un aperçu conservé et borné.
- Les artefacts d'Evidences sont limités au périmètre sélectionné, aux chemins
  confinés sans liens symboliques, avec un budget total de prévisualisation borné.
  Artefact, contrat, contrôles et décisions humaines restent séparés.
- Panneaux `CURRENT ACTIVITY`, `WORKFLOW`, `METRICS` ; distinction activité et
  lecture historique ; TODO natifs imbriqués et navigation fixe conservés.
- `Approval required` orange. Command Input conserve son composant, son cadre,
  sa hauteur et sa saisie slash. À faible hauteur, le sélecteur se compacte,
  laissant de la place au contenu tout en conservant le résumé du run.

## Validation et limite connue

- Nouveaux contrôles : `tests/test_run_selected_composition.py`, couvrant données
  manquantes, candidat périmé, lecture historique, ASCII, refus de chemins externes,
  action Ready/busy/indisponible, confirmations transmises, navigation des
  documents, conservation de sélection, dimensions et apparence de la commande.
- Vérification initiale ciblée : 103 tests de cockpit/frontières/services réussis.
- Trois régressions d'Entrée trouvées par la première suite complète ont été
  corrigées et leurs trois tests existants repassent. Les comportements des
  écrans Settings et de complétion/approbation initiale sont préservés.
- `compileall` et `git diff --check` : réussis.
- La suite complète garde **trois erreurs préexistantes** dans les trois sous-cas
  de `CliTests.test_readonly_research_retains_invalid_candidates_and_allows_retry`.
  Après réessai, ce test relit l'ancien chemin de la sortie rejetée et reçoit
  `FileNotFoundError`. Reproduit dans un export propre de `HEAD` antérieur à la
  refonte : **183 tests CLI, les mêmes trois erreurs**. Aucun changement moteur
  de conservation des artefacts n'est mélangé à cette refonte UI.

Passage complet de livraison, après correction du mode compact : **766 tests,
trois erreurs préexistantes, trois tests ignorés**, aucun échec d'assertion.
Commande : `PYTHONPATH=src .venv/bin/python -m unittest` ; journal :
`/tmp/loopforge-live-full-delivery.log`. La suite complète reste donc en échec
pour les trois sous-cas moteur décrits ci-dessus.

Le passage ciblé composition/frontières/services réussit ses **96 tests**.
Le contrôle final du retour Changes → Live et des nouveaux scénarios réussit
ses **10 tests**. Les six captures ont été régénérées après la dernière
correction : commande de quatre lignes conservée et coordonnées dans le
terminal vérifiées, notamment à 60 × 24 et 80 × 24.

Les journaux complets de travail restent sous `/tmp/loopforge-live-*.log`.
La [revue complémentaire](REVIEW.md) ajoute un test de gestion d'Entrée et
deux passages complets après correction : **767 tests par passage**, avec
les mêmes trois erreurs préexistantes et trois tests ignorés.
Les trois tests ignorés de la suite complète sont préexistants ; aucun nouveau
test n'est désactivé. Aucune revue humaine ni autorité de publication n'est
déduite de ces vérifications.
