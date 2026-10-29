"""Run the director: `uv run scripts/direct.py new "<story prompt>" --film my-film`. See `-h`."""

import sys

from director.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
