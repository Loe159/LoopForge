#!/bin/sh
# Install the latest LoopForge master in a dedicated user-owned environment.
set -eu

python_command=${LOOPFORGE_PYTHON:-python3}
install_dir=${LOOPFORGE_INSTALL_DIR:-"$HOME/.local/share/loopforge/venv"}
bin_dir=${LOOPFORGE_BIN_DIR:-"$HOME/.local/bin"}
install_source=${LOOPFORGE_INSTALL_SOURCE:-'git+https://github.com/Loe159/LoopForge.git@master'}
backup_launcher=false

command -v git >/dev/null 2>&1 || { echo 'Git is required.' >&2; exit 1; }
"$python_command" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11+ is required.")'

if [ -e "$bin_dir/loopforge" ] || [ -L "$bin_dir/loopforge" ]; then
    if [ ! -L "$bin_dir/loopforge" ] || [ "$(readlink "$bin_dir/loopforge")" != "$install_dir/bin/loopforge" ]; then
        # Recognize pip's old entry point even when its Python package is gone.
        # Never execute a broken launcher to identify it.
        if [ ! -L "$bin_dir/loopforge" ] && [ -f "$bin_dir/loopforge" ] && "$python_command" -c '
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
sys.exit(0 if "from loopforge.cli import main" in text and "sys.exit(main())" in text else 1)
' "$bin_dir/loopforge"; then
            backup_launcher=true
        else
            echo "Refusing to overwrite $bin_dir/loopforge: unrecognized command. Choose LOOPFORGE_BIN_DIR." >&2
            exit 1
        fi
    fi
fi

if [ ! -x "$install_dir/bin/python" ]; then
    "$python_command" -m venv "$install_dir"
fi
"$install_dir/bin/python" -m pip install --upgrade --force-reinstall "$install_source"
"$install_dir/bin/loopforge" --version
mkdir -p "$bin_dir"
if [ "$backup_launcher" = true ]; then
    backup_path=$(mktemp "$bin_dir/loopforge.backup.XXXXXX")
    cp -p "$bin_dir/loopforge" "$backup_path"
    printf 'Previous LoopForge launcher saved: %s\n' "$backup_path"
fi
ln -sfn "$install_dir/bin/loopforge" "$bin_dir/loopforge"
printf '\nLoopForge installed: %s/loopforge\nUpdate with: loopforge update\n' "$bin_dir"
case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add this directory to PATH in your shell configuration:\nexport PATH="%s:$PATH"\n' "$bin_dir" ;;
esac
