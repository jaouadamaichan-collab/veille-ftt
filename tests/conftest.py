import pytest

from tests.fake_supabase import FauxSupabase
from veille import seed, valider
from veille.db import Base


@pytest.fixture
def base():
    """Base en mémoire initialisée avec la vraie configuration, hypothèses activées."""
    db = Base(client=FauxSupabase())
    assert seed.main([], db=db) == 0
    assert valider.main(["--activer-proposees", "--motif", "test"], db=db) == 0
    return db
