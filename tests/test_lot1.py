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


# ───────────── Clé Supabase ─────────────

def _jwt(role):
    import base64, json
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'HS256'})}.{b({'role': role})}.sig"


def test_cle_publique_supabase_refusee():
    from veille.db import verifier_cle_serveur
    for cle in ("sb_publishable_abc", _jwt("anon")):
        with pytest.raises(RuntimeError):
            verifier_cle_serveur(cle)
    verifier_cle_serveur("sb_secret_abc")
    verifier_cle_serveur(_jwt("service_role"))


def _plan(n):
    return [{"requete": f"q{k}", "langue": "en", "source_id": "s", "origine": "serper"} for k in range(n)]


def test_refus_serper_bascule_tout_le_passage_sur_duckduckgo(monkeypatch):
    from veille import run_daily
    from veille.collect import ErreurSerper
    serper, ddg = [], []

    def refus(cle, requete, *a):
        serper.append(requete)
        raise ErreurSerper(400, '{"message":"Not enough credits","statusCode":400}')

    def ddg_ok(requete, *a):
        ddg.append(requete)
        return [{"url": f"https://x.com/{requete}"}]

    monkeypatch.setattr(run_daily, "rechercher_serper", refus)
    monkeypatch.setattr(run_daily, "rechercher_ddg", ddg_ok)
    monkeypatch.setattr(run_daily.time, "sleep", lambda s: None)
    monkeypatch.setenv("SERPER_API_KEY", "x")
    stats, erreurs = {"nb_requetes_serper": 0}, []
    items = run_daily.rechercher(_plan(5), config.parametres(), stats, erreurs)
    assert serper == ["q0"]                                  # un seul essai Serper
    assert ddg == ["q0", "q1", "q2", "q3", "q4"]             # la requête refusée est reprise par DuckDuckGo
    assert len(items) == 5 and stats["_nb_requetes_ddg"] == 5
    assert "Not enough credits" in erreurs[0] and "bascule" in erreurs[0]


def test_erreur_serper_ponctuelle_secourue_sans_bascule(monkeypatch):
    from veille import run_daily
    from veille.collect import ErreurSerper
    ddg = []

    def serper(cle, requete, *a):
        if requete == "q1":
            raise ErreurSerper(500, "erreur interne")
        return [{"url": requete}]

    monkeypatch.setattr(run_daily, "rechercher_serper", serper)
    monkeypatch.setattr(run_daily, "rechercher_ddg", lambda requete, *a: ddg.append(requete) or [])
    monkeypatch.setattr(run_daily.time, "sleep", lambda s: None)
    monkeypatch.setenv("SERPER_API_KEY", "x")
    stats = {"nb_requetes_serper": 0}
    run_daily.rechercher(_plan(3), config.parametres(), stats, [])
    assert ddg == ["q1"] and stats["nb_requetes_serper"] == 2


def test_duckduckgo_interrompu_apres_trois_echecs(monkeypatch):
    from veille import run_daily
    from veille.collect import ErreurSource
    appels = []

    def ddg_ko(requete, *a):
        appels.append(requete)
        raise ErreurSource("DuckDuckGo : RatelimitException")

    monkeypatch.setattr(run_daily, "rechercher_ddg", ddg_ko)
    monkeypatch.setattr(run_daily.time, "sleep", lambda s: None)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    erreurs = []
    run_daily.rechercher(_plan(10), config.parametres(), {"nb_requetes_serper": 0}, erreurs)
    assert len(appels) == 3 and "interrompu" in erreurs[-1] and "7 requête(s)" in erreurs[-1]


def test_rechercher_ddg_convertit_les_resultats(monkeypatch):
    import ddgs
    from veille.collect import rechercher_ddg

    class Faux:
        def news(self, q, **kw):
            assert kw == {"region": "fr-fr", "timelimit": "w", "max_results": 10}
            return [{"url": "https://www.meretmarine.com/a?utm_source=x", "title": "<b>GNL</b> à Marseille", "body": "Soutage", "date": "2026-11-09T08:00:00+00:00"},
                    {"url": "https://b.fr/c", "title": "Sans date", "body": "", "date": "il y a 2 heures"}]

    monkeypatch.setattr(ddgs, "DDGS", Faux)
    r = rechercher_ddg("site:meretmarine.com GNL", "fr", "meretmarine", "serper")
    assert r[0]["titre"] == "GNL à Marseille" and r[0]["domaine"] == "meretmarine.com"
    assert r[0]["publie_le"].startswith("2026-11-09") and r[1]["publie_le"] is None
