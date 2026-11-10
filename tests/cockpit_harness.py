import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.cockpit_donnees import base  # noqa: E402
from veille.cockpit import afficher  # noqa: E402

afficher(base())
