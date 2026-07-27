"""Allow ``python -m loopforge`` to dispatch to the CLI facade.

This module exists so that ``python -m loopforge version --json`` and similar
invocations work without requiring users to know the exact entry-point
function.  It delegates entirely to :func:`loopforge.cli.main` and exits with
the returned status code.
"""

from loopforge.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
