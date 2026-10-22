# Vérification du dossier de maquettes — 21/10/2026

Contrôles exécutés :

- Les 31 PNG se décodent et les 31 SVG sont valides XML.
- Les 31 transcriptions respectent leur largeur déclarée ; la scène
  60 × 24 en ASCII ne contient aucun caractère non ASCII dans la TUI.
- Les ressources et liens de la galerie pointent vers des fichiers locaux
  existants ; aucune dépendance distante n'est nécessaire.
- Inspection groupée de la planche des 31 compositions et de vues détaillées,
  puis confirmation des corrections de grille, source de session, commande
  et distinction entre activité et sélection.
- Galerie exécutée dans Firefox headless : 31 aperçus et six groupes de choix,
  aucun choix présélectionné ; agrandissement, image suivante, zoom,
  fermeture et génération du retour groupé vérifiés.
- Rechargement : les choix temporaires disparaissent, conformément à
  l'absence de stockage automatique. Aucun avis de test n'est conservé.
- Galerie à 1440 pixels puis à 500 pixels de largeur effective : aucun
  débordement horizontal de la page. Firefox limite la fenêtre demandée à
  390 pixels à une largeur effective de 500 ; aucun contrôle à 390 n'est affirmé.
- `git diff --check` : réussi.

Le téléchargement `.txt` est déclenché seulement au clic utilisateur ; le
parcours automatisé a vérifié la génération du contenu à copier, sans déclencher
de téléchargement. Aucune approbation produit n'est enregistrée par ces contrôles.

Ces vérifications portent sur les artefacts et la galerie, **pas sur Textual**.
Pas de modification du code produit ; aucune suite Python/CLI n'a été exécutée
pour ces seuls fichiers de conception. La recette TUI réelle reste à faire
après validation puis implémentation des choix.
