# Textual UI Pilot

## Mission

Tester rapidement et de façon déterministe la navigation, les modals et la synchronisation des snapshots avec `LoopForgeApp.run_test()`.

## Règles

- Utiliser `Pilot.press`, `resize_terminal` et `pause` ; ne pas appeler directement une action lorsque la touche publique existe.
- Une action directe est permise seulement pour préparer un état non accessible dans le scénario ciblé, et doit être déclarée.
- Attendre une condition d'état, jamais une durée arbitraire seule.
- Vérifier l'écran logique, les widgets visibles, le texte essentiel, la sélection, la révision et l'opération.
- Tester 60, 80, 120 et 160 colonnes.
- Capturer un dump avant et après chaque modal.
- Ne pas utiliser OCR ou snapshot pixel comme oracle principal.

## Sortie

Chronologie des touches, dumps DOM/texte, état de l'application et assertions.
