# Skill: PTY User Simulation

Lance une commande dans un pseudo-terminal, envoie des touches et reconstruit des frames lisibles.

## Capacités

- attente de motif avec timeout ;
- touches normales et contrôles ;
- redimensionnement ;
- capture ANSI brute ;
- normalisation de l'écran courant ;
- détection de processus fils ;
- arrêt progressif Ctrl+C puis kill du groupe.

Sous Windows, utiliser ConPTY ou une bibliothèque équivalente ; sous Unix, `pty`/`pexpect`.
