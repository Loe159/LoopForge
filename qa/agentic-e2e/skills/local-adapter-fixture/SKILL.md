# Skill: Local Adapter Fixture

Réutilise l'adapter produit `local-adapter-fixture` et le wrapper `local_implementation_adapter.py`. Ce skill ne crée aucun adapter supplémentaire.

## Entrées

- stage demandé : research, plan, implementation ou review ;
- prompt LoopForge reçu sur stdin ;
- identifiant de scénario ;
- mode déclaré ;
- chemins de fixture et de preuve autorisés.

## Comportement nominal

- research : écrire sur stdout un artefact de recherche valide et ne modifier aucun fichier ;
- plan : écrire sur stdout un plan valide avec fichiers autorisés et commande de test ;
- implementation : modifier uniquement le fichier prévu dans le workspace ;
- review : écrire sur stdout une review valide et ne modifier aucun fichier.

## Modes d'échec

`blocked`, `invalid-artifact`, `nonzero-exit`, `slow`, `partial-write`, `out-of-scope-patch`, `negative-review`.

## Oracle

Chaque invocation écrit un journal JSON dans le dossier de preuves avec stage, rôle, arguments, cwd, fichiers lus/écrits, exit code et mode. Le skill refuse le réseau, le shell, toute écriture hors workspace pendant implementation et toute écriture pendant les stages read-only.

Pour implementation, l'auditeur vérifie également le contrat de `result.json` produit par le wrapper existant.
