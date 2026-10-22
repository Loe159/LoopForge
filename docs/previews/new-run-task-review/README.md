# New Run / Task — revue des deux designs

**Statut : design A retenu le 22 octobre 2026, puis implémentation autorisée.**

Tâche et critères sont réunis sur une page. Le retour de design ne déclenchait
aucune implémentation ni approbation moteur ; l'instruction suivante « Fais
l'implémentation » a autorisé le travail produit. Voir la
[livraison locale et les captures natives](../new-run-task-implementation/README.md).
La galerie conserve les deux propositions
pour comparaison et son formulaire initial sans choix présélectionné ; la
décision reçue est enregistrée dans `decisions.json` et dans le plan UX.

[Ouvrir la galerie](index.html) · [Plan UX](../../plans/2026-10-21-005-new-run-task-redesign.md)
· [Vérification et limites](VERIFICATION.md)

- **A :** tâche multiligne et critères sur une page.
- **B :** décrire la tâche, puis préciser les critères ; création à la fin.
- **Suite commune :** consultation de Task, complétion éventuelle avec
  « Save criterion », puis approbation explicite par l'action moteur existante.

Les 19 maquettes sont des dessins sur une grille terminal, avec données
fictives. Les images ne sont pas une capture d'une fonctionnalité implémentée.
La capture `assets/current-entry-120.*` montre séparément le composant Textual
actuel, ouvert au-dessus d'une fixture synthétique, sans opération moteur.

Les formats PNG, SVG et texte sont référencés dans `manifest.json`.
`overview.png` est une planche de lecture rapide ; les fichiers individuels
permettent l'inspection à taille réelle. La galerie propose agrandissement,
transcription, navigation clavier et un retour groupé à copier ou exporter.
Elle utilise seulement des fichiers locaux : aucun serveur, appel réseau,
stockage automatique ni dépendance externe. Recharger perd les choix non
exportés. Un clic d'export télécharge seulement un fichier texte.

Le design terminal hérite de DESIGN.md et de Live : cadres carrés, monospace,
palette graphite violet, lavande pour le focus, orange pour l'attention et
l'approbation. L'interface proposée reste en anglais, les explications de revue
en français. Aucun nouveau pack, outil, permission ou automatisme n'est ajouté.

Les critères peuvent être reportés jusqu'à Task ; leur présence est nécessaire
avant approbation selon le validateur moteur. En profil autonomous, la grille
subjective est recueillie avant création quand le moteur l'exige. Les maquettes
ne promettent aucune édition générale des tâches déjà enregistrées ni réparation
d'une grille manquante dans un ancien run : l'API actuelle ne le permet pas.

Un brouillon reste en mémoire pendant la saisie, sans sauvegarde durable.
Créer un run, enregistrer un critère, approuver Task et exécuter Research restent
des actions distinctes. Aucun critère saisi n'est présenté comme une preuve.

`decisions.json` conserve le choix **A** et l'autorisation ultérieure
d'implémentation. Aucune approbation moteur n'est déduite de ces décisions.
