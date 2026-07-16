# Invariants à vérifier après chaque étape

## Sécurité et autorité

1. Research, plan et review ne modifient aucun fichier suivi dans le worktree projet.
2. L'implémentation ne commence jamais avant approbation du plan.
3. Une vérification réussie n'approuve pas la review.
4. Un rapport de reviewer ne vaut pas approbation humaine.
5. La publication ne pousse aucune branche et n'ouvre aucune PR réseau.
6. Les chemins protégés du pack ne sont jamais modifiés silencieusement.
7. Les actions annulées ne changent pas les gates.

## Persistance

1. Chaque run garde un `run_id` stable lors d'une reprise.
2. L'état écrit est lisible après redémarrage du processus.
3. Les artefacts validés existent, sont non vides et correspondent à l'étape.
4. Un échec conserve le dernier état cohérent et la prochaine action de récupération.
5. Les runs de deux projets ayant le même basename restent séparés par `project_id`.
6. L'archive conserve les artefacts et n'est pas présentée comme une opération active.

## Interface

1. L'écran affiché correspond au projet et run sélectionnés.
2. La prochaine action visible correspond à l'action éligible du moteur.
3. Les couleurs ne sont jamais la seule indication.
4. Aucun spinner ne boucle après la fin d'une opération.
5. Une opération de fond ne bloque pas les touches d'annulation.
6. Les listes restent bornées et navigables à 60, 80, 120 et 160 colonnes.

## Sorties CLI

1. JSON et CSV ne contiennent ni ANSI, ni prompts, ni texte décoratif.
2. Les erreurs et progressions ne polluent pas stdout machine.
3. `--no-input` ne valide aucune gate et n'exécute aucun adapter.
4. `TERM=dumb`, `NO_COLOR` et `LOOPFORGE_ASCII=1` restent lisibles.
