"""`python -m pipeline`'s process entry point.

Holds nothing but the two lines that hand off to `pipeline.cli.main`. Every
argument-parsing rule, every exit code, and every subcommand lives in
`pipeline.cli`, which a test imports and calls directly with its own `argv`
list -- so this file has nothing to test itself, and adding logic here would
only be logic a test could not reach without spawning a real process.
"""

import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
