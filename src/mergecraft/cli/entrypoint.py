"""Process entrypoint with a lightweight, standalone version query.

Exports:
    main: Run the CLI, loading its command parser only when needed.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Print an isolated version query, or run the full CLI parser.

    The exact one-option form needs neither repository credentials nor logging.
    Other forms retain normal Click validation and global-option handling.
    """
    if sys.argv[1:] in (["--version"], ["-v"]):
        import mergecraft

        print(mergecraft.format_version_display(mergecraft.__version__, mergecraft.__commit__))
        return
    from mergecraft.cli.app import main as run_cli

    run_cli()


if __name__ == "__main__":
    main()
