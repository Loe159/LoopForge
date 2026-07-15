# Fixtures UX de la phase 0

Ces jeux de données figent les contrats avant la refonte de l’interface :

- `phase0-state-matrix.json` contient les états visibles, leurs snapshots
  plain/Rich et leur future famille de présentation ;
- `phase0-machine-contracts.json` décrit les sorties JSON/CSV et codes de
  retour actuels ;
- `projects/` représente deux dépôts distincts qui portent tous deux le nom
  `LoopForge`.

Les deux configurations homonymes partagent intentionnellement le même
`run_root`. C’est le défaut historique à préserver comme référence de test en
phase 0 ; la phase 2 le remplacera par une identité de projet et une migration
non destructive.
