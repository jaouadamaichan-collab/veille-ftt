"""Tests hors ligne du lot 1 (aucune clé, aucun réseau)."""

from datetime import date

import pytest

from veille import config
from veille.collect import nettoyer, requetes_du_jour
from veille.dedup import domaine_de, normaliser_url, rapprocher
from veille.llm import Budget, BudgetEpuise, extraire_json
from veille.triage import construire_message, construire_systeme, valider_resultats


# ───────────── Configuration ─────────────

def test_configuration_coherente():
    assert config.valider() == []


def test_chaque_question_a_deux_hypotheses_et_une_contre():
    for q in config.domaine()["questions"]:
        hs = [h for h in config.hypotheses() if h["question"] == q["id"]]
        assert sum(h["type"] == "hypothese" for h in hs) >= 2
        assert sum(h["type"] == "contre" for h in hs) >= 1


@pytest.mark.parametrize(
    "titre, attendu",
    [
        ("IMO talks on net-zero framework stall", True),
        ("FuelEU pooling prices climb", True),
        ("Le GNL domine les commandes", True),
        ("Nouvelle usine de méthanol vert à Dunkerque", True),
        ("Pirates attack tanker off Somalia", False),
        ("Company reports record assets this quarter", False),   # « ets » dans « assets » ne doit pas passer
        ("Débat sur l'économie bretonne", False),               # « omi » dans « économie » ne doit pas passer
    ],
)
def test_prefiltre(titre, attendu):
    assert config.passe_prefiltre(titre, "") is attendu


# ───────────── Dédoublonnage ─────────────

def test_normaliser_url_retire_tracking_et_www():
    a = normaliser_url("http://www.Splash247.com/article/?utm_source=x&id=3#top")
    b = normaliser_url("https://splash247.com/article?id=3")
    assert a == b


def test_domaine_de():
    assert domaine_de("https://climate.ec.europa.eu/news/x") == "ec.europa.eu"
    assert domaine_de("https://www.bbc.co.uk/news") == "bbc.co.uk"
    assert domaine_de("https://gcaptain.com/a") == "gcaptain.com"


POOL = [
    {
        "id": 1,
        "evenement_id": 10,
        "reprise_de": None,
        "titre": "IMO delays adoption of net-zero framework by one year",
        "extrait": "Member states voted to adjourn the extraordinary session after Saudi Arabia motion backed by the United States.",
        "domaine": "gcaptain.com",
    }
]


def test_meme_media_titre_quasi_identique_est_un_doublon():
    item = {"titre": "IMO delays adoption of net-zero framework by one year", "extrait": "", "domaine": "gcaptain.com"}
    assert rapprocher(item, POOL).doublon


def test_autre_media_meme_depeche_est_une_reprise():
    item = {
        "titre": "IMO delays adoption of net-zero framework by one year",
        "extrait": "Member states voted to adjourn the extraordinary session after Saudi Arabia motion backed by the United States.",
        "domaine": "hellenicshippingnews.com",
    }
    r = rapprocher(item, POOL)
    assert not r.doublon and r.evenement_id == 10 and r.reprise_de == 1


def test_autre_media_redaction_differente_est_une_source_independante():
    item = {
        "titre": "Net-zero framework: IMO adoption delayed, shipping faces one more year of uncertainty",
        "extrait": "Shipowners and fuel suppliers react to the postponement, warning about investment decisions.",
        "domaine": "splash247.com",
    }
    r = rapprocher(item, POOL)
    assert r.evenement_id == 10 and r.reprise_de is None


def test_sujet_different_cree_un_nouvel_evenement():
    item = {"titre": "Maersk orders eight LNG dual-fuel containerships", "extrait": "", "domaine": "splash247.com"}
    r = rapprocher(item, POOL)
    assert r.evenement_id is None and not r.doublon


def test_une_reprise_de_reprise_pointe_vers_l_original():
    pool = POOL + [{**POOL[0], "id": 2, "reprise_de": 1, "domaine": "hellenicshippingnews.com"}]
    item = {**POOL[0], "domaine": "marinelink.com"}
    item.pop("id")
    assert rapprocher(item, pool).reprise_de == 1


# ───────────── Collecte ─────────────

def test_nettoyer_html():
    assert nettoyer("<p>LNG &amp; <b>methanol</b></p>") == "LNG & methanol"


def test_rotation_couvre_toutes_les_requetes_en_trois_jours_et_respecte_le_plafond():
    sources = [{"id": f"s{n}", "requete": f"q{n}", "langue": "en"} for n in range(9)]
    indicateurs = [{"id": f"H-{n}", "requete": f"i{n}"} for n in range(27)]
    vues = set()
    for k in range(3):
        plan = requetes_du_jour(sources, indicateurs, date(2026, 11, 9 + k), maximum=100)
        vues |= {r["requete"] for r in plan}
    assert len(vues) == 36
    assert len(requetes_du_jour(sources, indicateurs, date(2026, 11, 9), maximum=5)) == 5


def test_source_sans_requete_ignoree():
    plan = requetes_du_jour([{"id": "serper_indicateurs", "requete": None}], [], date(2026, 11, 9), 10, periode=1)
    assert plan == []


# ───────────── LLM ─────────────

def test_budget_plafonne_les_appels():
    b = Budget(2)
    b.consommer()
    b.consommer()
    with pytest.raises(BudgetEpuise):
        b.consommer()


def test_extraire_json_avec_bloc_markdown():
    assert extraire_json('Voici :\n```json\n[{"i": 0}]\n```') == [{"i": 0}]
    assert extraire_json('[{"i": 0, "x": {"a": 1}}] fin') == [{"i": 0, "x": {"a": 1}}]


# ───────────── Tri ─────────────

IND = {"H2-A": [{"id": "H2-A-1", "description": "d", "sens": "confirme"}], "H2-B": [{"id": "H2-B-1", "description": "d", "sens": "confirme"}]}
LOT = [
    {"id": 101, "titre": "a", "extrait": "", "domaine": "x.com", "echiquier_source": "concurrentiel"},
    {"id": 102, "titre": "b", "extrait": "", "domaine": "y.com", "echiquier_source": "institutionnel"},
    {"id": 103, "titre": "c", "extrait": "", "domaine": "z.com", "echiquier_source": "concurrentiel"},
]


def test_validation_filtre_les_identifiants_inventes():
    brut = [
        {
            "i": 0, "pertinent": True, "score": 15, "echiquier": "institutionnel", "questions": ["Q2", "Q9"],
            "liens": [
                {"hypothese": "H2-A", "indicateur": "H2-A-1", "relation": "soutient", "justification": "fait"},
                {"hypothese": "H9-Z", "indicateur": None, "relation": "soutient", "justification": "inventé"},
                {"hypothese": "H2-B", "indicateur": "H2-A-1", "relation": "contredit", "justification": "fait 2"},
                {"hypothese": "H2-A", "indicateur": None, "relation": "contredit", "justification": "doublon"},
            ],
            "resume": "r",
        },
        {"i": 1, "pertinent": True, "score": 6, "echiquier": "lune", "questions": [], "liens": [], "resume": "r"},
    ]
    r = valider_resultats(brut, LOT, {"Q1", "Q2", "Q3"}, IND)
    a, b, c = r
    assert a["score"] == 10 and a["questions"] == ["Q2"]
    assert [(l["hypothese_id"], l["indicateur_id"]) for l in a["liens"]] == [("H2-A", "H2-A-1"), ("H2-B", None)]
    assert a["hors_radar"] is False
    assert b["echiquier"] == "institutionnel"          # échiquier invalide → celui de la source
    assert b["hors_radar"] is True                     # pertinent sans lien = hors radar (D20)
    assert c == {"signal_id": 103, "trie": False}      # absent de la réponse → repris au prochain passage


def test_lien_sans_justification_ou_non_pertinent_rejete():
    brut = [
        {"i": 0, "pertinent": True, "score": 5, "liens": [{"hypothese": "H2-A", "relation": "soutient", "justification": ""}]},
        {"i": 1, "pertinent": False, "score": 9, "liens": [{"hypothese": "H2-A", "relation": "soutient", "justification": "x"}]},
    ]
    r = valider_resultats(brut, LOT[:2], {"Q2"}, IND)
    assert r[0]["liens"] == [] and r[1]["liens"] == []
    assert r[1]["score"] <= 3 and r[1]["hors_radar"] is False


def test_prompt_contient_hypotheses_indicateurs_et_regles():
    hs = [{**h, "question_id": h["question"]} for h in config.hypotheses()]
    ind = {h["id"]: h["indicateurs"] for h in config.hypotheses()}
    s = construire_systeme(config.domaine(), hs, ind)
    for h in config.hypotheses():
        assert h["id"] in s
    assert "H2-A-3 [infirme]" in s
    assert "CONTREDISENT" in s and "N'invente rien" in s
    m = construire_message(LOT[:1])
    assert '"i": 0' in m
