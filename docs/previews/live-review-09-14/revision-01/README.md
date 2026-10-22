# Composition ajustée après retour utilisateur

[Ouvrir les huit maquettes ajustées](index.html).

Choix enregistrés : **9A / 10B / 11B / 12A / 13A**, assemblés dans le cockpit.
Ce dossier remplace la recommandation initiale 9C/10A/11A/12B/13B. Il ne
déclenche aucune implémentation ni approbation moteur.

- Execution Result A sans les boutons Changes/Evidences.
- Context B et Evidences B intégrés avec la supervision retenue.
- Supervision A : `CURRENT ACTIVITY`, `WORKFLOW`, `METRICS` en capitales.
- Commande A : `Approval required` orange ; Command Input actuel conservé
  (cadre lavande, surface, titre, ligne de saisie, ligne de suggestions).
- Proposition pour la suite : un seul bandeau Next step persistant au-dessus
  de la commande, activé par le raccourci moteur existant `Ctrl+Enter`.

La proposition Next step répond à la priorité de déclenchement exprimée par
l'utilisateur ; elle reste une proposition d'interaction. Le reçu ne démarre
pas un agent, le changement de vue ne déclenche rien et le moteur conserve
l'éligibilité et les confirmations. Les boutons des autres vues, comme
`Open artifact`, ne sont pas concernés par le retrait dans Execution Result.

Le panneau d'action peut grandir d'une ligne pour afficher un libellé moteur
long sans le tronquer. Cette adaptation ne remplace pas le Command Input.
La fixture de fin contient quatre TODO explicitement complétés ; les autres
fixtures gardent leurs états natifs fictifs.

[Décisions détaillées et frontières d'implémentation](../../../plans/2026-10-21-004-live-selected-composition.md).
Les préférences sont aussi consignées dans [choices.json](choices.json).

Images statiques, données fictives. Aucun code de l'interface modifié.
