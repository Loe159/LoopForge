# Politique d'exécution

## Isolation

Pour chaque scénario :

```text
<campaign>/sandboxes/<scenario-id>/
  repo/
  loopforge-home/
  temp/
  evidence/
  fixture-control/
```

Variables minimales :

```text
LOOPFORGE_HOME=<scenario>/loopforge-home
TMPDIR=<scenario>/temp
PYTHONUNBUFFERED=1
```

Ne partager ni registry, ni run, ni workspace entre scénarios.

## Chemin déterministe existant

Le parcours obligatoire sélectionne l'adapter produit `local-adapter-fixture` et lui passe une commande Python absolue :

```text
loopforge shell --command "/adapter local-adapter-fixture -- <python> <fixture.py> --scenario S01"
```

Le harnais ne doit pas ajouter un autre adapter ou un autre wrapper.

### Étapes read-only

Research, plan et review utilisent le chemin read-only existant du moteur :

1. `command_for_readonly_stage()` conserve la commande de `local-adapter-fixture` ;
2. l'exécutable est résolu sans shell ;
3. le processus est exécuté par le helper isolé ;
4. le prompt est fourni sur stdin ;
5. stdout doit contenir uniquement l'artefact Markdown attendu ;
6. le worktree doit rester strictement inchangé.

### Étape implementation

L'implementation utilise le chemin existant :

1. le moteur crée `expected-session.json` et le prompt d'attempt ;
2. `src/loopforge/adapters/local_implementation_adapter.py` exécute la commande fixture ;
3. la politique autorise Python uniquement lorsque le `runner_id` vaut `local-adapter-fixture` ;
4. le wrapper exige un workspace propre, un workspace correspondant à la session et une commande sans shell ;
5. le résultat est validé par le schéma existant puis enregistré sous l'attempt ;
6. un changement attendu mène à `ready_for_verification`, l'absence de changement à `adapter_blocked`.

## Commande fixture déterministe

La commande de fixture appartient au harnais, pas au moteur. Elle doit :

- lire le prompt sur stdin ;
- identifier le stage demandé à partir du prompt et des arguments explicites ;
- produire `research.md`, `plan.md` ou `review.md` sur stdout pour les stages read-only ;
- appliquer un petit patch prédéfini pour implementation ;
- ne jamais accéder au réseau ;
- accepter des modes d'échec explicites par argument ou fichier de contrôle ;
- écrire sa trace structurée uniquement dans le dossier de preuves autorisé ;
- refuser tout stage ou scénario non déclaré.

Modes minimum : `nominal`, `blocked`, `invalid-artifact`, `nonzero-exit`, `slow`, `partial-write`, `out-of-scope-patch`, `negative-review`.

## Adapters réels

Un smoke test réel est exécuté uniquement si l'exécutable est présent. Il vérifie le dispatch et l'agent sélectionné, mais ne décide pas du verdict obligatoire de la campagne.

## Timeouts

- action UI instantanée : 2 s ;
- chargement projet/run : 10 s ;
- étape fixture déterministe : 30 s ;
- suite de vérification fixture : 60 s ;
- adapter réel : timeout configuré séparément.

Tout timeout capture d'abord l'écran, les événements et les processus enfants, puis annule proprement.

## Parallélisme

Paralléliser seulement les scénarios totalement isolés. Les actions d'un même parcours restent séquentielles pour conserver une chronologie fiable.
