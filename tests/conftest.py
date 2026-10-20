import sys
from pathlib import Path

# Scripts are not a package; make them importable for tests of their pure functions.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
