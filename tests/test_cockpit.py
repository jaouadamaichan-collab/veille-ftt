"""Tests du cockpit avec streamlit.testing (exécution réelle des pages, clics compris)."""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
from tests import cockpit_donnees  # noqa: E402

HARNAIS = str(Path(__file__).with_name("cockpit_harness.py"))


@pytest.fixture
def app():
    cockpit_donnees.ETAT.clear()
    at = st_testing.AppTest.from_file(HARNAIS, default_timeout=20)
    at.run()
    assert not at.exception, at.exception
    return at


def aller(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, at.exception
    return at


def bouton(at, libelle):
    return next(b for b in at.button if b.label == libelle)


def test_toutes_les_pages_s_affichent(app):
    for page in ("Brief de la semaine", "Hypothèses", "Liens à statuer", "Sources", "Journal"):
        aller(app, page)
        assert app.title[0].value == page


def test_appliquer_une_suggestion_historise_la_decision(app):
    db = cockpit_donnees.base()
    aller(app, "Brief de la semaine")
    bouton(app, "Appliquer : affaiblie").click().run()
    assert not app.exception
    h = db.t("hypotheses").select("*").eq("id", "H2-A").execute().data[0]
    assert h["statut"] == "affaiblie"
    v = db.t("hypotheses_versions").select("*").eq("hypothese_id", "H2-A").order("cree_le", desc=True).execute().data
    assert v[0]["auteur"] == "humain" and "report du vote" in v[0]["motif"]
    # La suggestion bridée (« maintenir ») n'offre pas de bouton
    assert not any(b.label.startswith("Appliquer : maintenir") for b in app.button)


def test_archiver_et_valider_le_brief(app):
    db = cockpit_donnees.base()
    aller(app, "Brief de la semaine")
    bouton(app, "Archiver H3-C").click().run()
    assert db.t("hypotheses").select("*").eq("id", "H3-C").execute().data[0]["statut"] == "archivee"
    bouton(app, "Valider ce brief").click().run()
    assert db.brief("2026-11-16")["statut"] == "valide"


def test_statuer_les_liens(app):
    db = cockpit_donnees.base()
    aller(app, "Liens à statuer")
    assert app.sidebar.metric[0].value == "2"
    bouton(app, "Valider").click().run()                       # le plus récent d'abord : lien 2
    assert db.t("liens").select("*").eq("id", 2).execute().data[0]["statut"] == "valide"
    app.selectbox(key="motif-1").set_value("mauvaise_lecture").run()
    bouton(app, "Rejeter").click().run()
    l1 = db.t("liens").select("*").eq("id", 1).execute().data[0]
    assert (l1["statut"], l1["motif_rejet"]) == ("rejete", "mauvaise_lecture")
    assert app.sidebar.metric[0].value == "0"


def test_changement_de_statut_sans_motif_refuse(app):
    db = cockpit_donnees.base()
    aller(app, "Hypothèses")
    # Premier formulaire « Changer le statut » = H1-A
    app.selectbox[0].set_value("renforcee")
    next(b for b in app.button if b.label == "Enregistrer").click().run()
    assert app.error and "motif" in app.error[0].value.lower()
    assert db.t("hypotheses").select("*").eq("id", "H1-A").execute().data[0]["statut"] == "active"


def test_ajouter_une_hypothese(app):
    db = cockpit_donnees.base()
    aller(app, "Hypothèses")
    app.text_area[-1].input("Les e-carburants restent marginaux dans le maritime jusqu'en 2035.")
    app.text_input[-1].input("Coûts de production")
    bouton(app, "Ajouter").click().run()
    assert not app.exception
    assert db.t("hypotheses").select("*").eq("id", "H1-D").execute().data


ENTREE = str(Path(__file__).resolve().parent.parent / "cockpit" / "app.py")


def test_entree_signale_les_secrets_manquants_par_leur_nom():
    at = st_testing.AppTest.from_file(ENTREE, default_timeout=20)
    at.secrets["SUPABASE_URL"] = "https://x.supabase.co"
    at.run()
    assert "SUPABASE_SERVICE_KEY" in at.error[0].value and "MOT_DE_PASSE" in at.error[0].value
    assert "SUPABASE_URL" not in at.error[0].value.split(":", 1)[1]


def test_entree_refuse_un_mauvais_mot_de_passe():
    at = st_testing.AppTest.from_file(ENTREE, default_timeout=20)
    at.secrets.update({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "sb_secret_x", "MOT_DE_PASSE": "bon"})
    at.run()
    at.text_input[0].input("mauvais").run()
    assert at.error[0].value == "Mot de passe incorrect."
    assert "authentifie" not in at.session_state
    assert not at.title or at.title[0].value == "Veille F-T-T"      # aucune page du cockpit affichée
