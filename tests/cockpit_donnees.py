"""Base en mémoire partagée entre les exécutions successives du cockpit dans AppTest."""

from tests.fake_supabase import FauxSupabase
from veille import seed, valider
from veille.db import Base

ETAT = {}


def base() -> Base:
    if "db" not in ETAT:
        db = Base(client=FauxSupabase())
        seed.main([], db=db)
        valider.main(["--activer-proposees", "--motif", "test"], db=db)
        db.t("signaux").insert([
            {"url": "https://gcaptain.com/a", "url_norm": "a", "titre": "IMO vote postponed", "domaine": "gcaptain.com", "echiquier": "institutionnel", "pertinent": True, "score": 8, "source_id": "gcaptain"},
            {"url": "https://imo.org/b", "url_norm": "b", "titre": "IMO statement", "domaine": "imo.org", "echiquier": "institutionnel", "pertinent": True, "score": 7, "source_id": "serper_imo"},
        ]).execute()
        db.t("liens").insert([
            {"signal_id": 1, "hypothese_id": "H2-A", "relation": "contredit", "justification": "Le vote est reporté."},
            {"signal_id": 2, "hypothese_id": "H2-B", "relation": "soutient", "justification": "Déclaration de l'OMI."},
        ]).execute()
        contenu = {
            "semaine": "2026-11-16", "synthese": "s",
            "mouvements": [{"titre": "OMI : report", "suggestions": [
                {"hypothese": "H2-A", "statut_suggere": "affaiblie", "motif": "report du vote"},
                {"hypothese": "H2-B", "statut_suggere": "maintenir", "motif": "bridée"}]}],
            "suggestions_archivage": [{"hypothese": "H3-C", "motif": "Aucun signal", "depuis": "2026-09-01"}],
        }
        db.enregistrer_brief("2026-11-16", contenu, "# Brief de veille — semaine du 16 novembre 2026\n\n## 1. OMI : report")
        db.t("runs").insert({"type": "daily", "statut": "partiel", "erreurs": ["Serper refuse"]}).execute()
        ETAT["db"] = db
    return ETAT["db"]
