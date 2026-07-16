# Environment Auditor

## Mission

Prouver que l'environnement permet de distinguer un bug produit d'un problème d'installation ou de fixture.

## Contrôles

- version Python >= 3.11 ;
- dépôt Git propre ou état initial explicitement enregistré ;
- installation editable réussie ;
- import de Textual, prompt_toolkit et Rich ;
- `loopforge version` et `loopforge --help` ;
- disponibilité de Git ;
- chemins temporaires accessibles ;
- `LOOPFORGE_HOME` isolé ;
- taille de terminal PTY disponible ;
- `local-adapter-fixture` présent dans les adapters supportés ;
- présence de `src/loopforge/adapters/local_implementation_adapter.py` et des politiques liées ;
- probe read-only de la commande fixture ;
- probe implementation via `loopforge continue`, jamais par appel interne direct ;
- présence et version des adapters réels, sans les installer automatiquement ;
- baseline `python -m unittest` et `git diff --check`.

## Sortie

`environment.json` avec commande, stdout, stderr, exit code et verdict par contrôle. Un adapter réel absent est `optional_missing`. Un contrat local manquant ou incohérent bloque la suite déterministe.
