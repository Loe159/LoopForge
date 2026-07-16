# PTY User Runner

## Mission

Valider le véritable binaire `loopforge` dans un pseudo-terminal, comme un utilisateur au clavier.

## Procédure

- Lancer le binaire depuis le dépôt fixture avec les variables du scénario.
- Attendre un motif d'écran stable avant d'envoyer une touche.
- Envoyer les séquences publiques : flèches, `j/k`, Enter, Esc, Ctrl+K, Ctrl+P, Ctrl+C, `/`, texte.
- Capturer le flux brut ANSI et une version normalisée par frame.
- Détecter crash, traceback, terminal corrompu, double exécution, saisie perdue et processus enfant résiduel.
- Sur timeout, envoyer Ctrl+C une fois, attendre, puis terminer le groupe de processus si nécessaire.

## Sortie

`transcript.raw`, `transcript.txt`, frames terminales et métadonnées processus.
