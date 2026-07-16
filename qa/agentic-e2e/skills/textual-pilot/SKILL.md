# Skill: Textual Pilot

## Helpers attendus

- `wait_for_screen(name)` ;
- `wait_for_revision(min_revision)` ;
- `wait_for_operation_finished()` ;
- `press_and_checkpoint(keys, checkpoint)` ;
- `dump_app_state()` ;
- `dump_visible_text()` ;
- `assert_no_traceback()`.

## Oracle

Toujours combiner au moins deux signaux : état interne publié et contenu visible. Ne pas dépendre d'une durée fixe ou d'une couleur seule.
