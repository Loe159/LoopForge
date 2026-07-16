# Skill: Workflow State Audit

À chaque checkpoint, produire un snapshot normalisé de :

- config projet et project id ;
- run id, état, stage, acteur et next action ;
- gates et approbations ;
- liste et empreinte des artefacts ;
- git status/diff ;
- workspace ;
- publication locale ;
- processus actifs associés.

Comparer le snapshot avec les invariants de `workflow/03-invariants.md` et retourner des violations structurées.
