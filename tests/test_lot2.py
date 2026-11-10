"""Tests hors ligne du lot 2 : analyse, avocat du diable, brief, décisions, passage hebdomadaire."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from veille import analyse, avocat, brief, config, decisions, mail, run_daily, run_weekly
from veille.llm import Budget

MAINTENANT = datetime(2026, 11, 16, 7, 0, tzinfo=timezone.utc)


# ───────────── Nature des sources et corroboration (D18) ─────────────

@pytest.mark.parametrize(
    "domaine, echiquier, attendu",
    [
        ("ec.europa.eu", None, "institution"),
        ("imo.org", None, "institution"),
        ("mer.gouv.fr", None, "institution"),
        ("epa.gov", None, "institution"),
        ("transportenvironment.org", None, "societe_civile"),
        ("blog.inconnu.org", "societe_civile", "societe_civile"),
        ("gcaptain.com", "concurrentiel", "presse"),
        ("monsieur-gouv.fr.example.com", None, "presse"),
    ],
)
def test_nature_source(domaine, echiquier, attendu):
    assert analyse.nature_source(domaine, echiquier) == attendu


def _s(i, domaine, nature, **kw):
    return {"id": i, "domaine": domaine, "nature": nature, "reprise_de": None, "fiabilite": "fiable", **kw}


def test_deux_titres_de_presse_ne_suffisent_pas():
    c = analyse.corroboration([_s(1, "gcaptain.com", "presse"), _s(2, "splash247.com", "presse")])
    assert c["domaines_independants"] == 2 and not c["suffisante"]


def test_presse_et_institution_suffisent():
    assert analyse.corroboration([_s(1, "gcaptain.com", "presse"), _s(2, "ec.europa.eu", "institution")])["suffisante"]


def test_reprise_et_source_douteuse_ne_comptent_pas():
    c = analyse.corroboration([
        _s(1, "gcaptain.com", "presse"),
        _s(2, "ec.europa.eu", "institution", reprise_de=1),
        _s(3, "imo.org", "institution", fiabilite="douteuse"),
    ])
    assert c["domaines_independants"] == 1 and not c["suffisante"] and c["nb_signaux"] == 3


def test_echiquiers_silencieux():
    comptes, silencieux = analyse.echiquiers_silencieux([
        {"pertinent": True, "echiquier": "concurrentiel"},
        {"pertinent": False, "echiquier": "institutionnel"},
    ])
    assert comptes["concurrentiel"] == 1 and silencieux == ["institutionnel", "societe_civile"]


def test_archivage_suggere_apres_six_semaines_seulement_si_analysee():
    vieux = (MAINTENANT - timedelta(weeks=7)).isoformat()
    recent = (MAINTENANT - timedelta(weeks=2)).isoformat()
    hs = [
        {"id": "H1-A", "statut": "active", "dernier_signal_le": vieux},
        {"id": "H1-B", "statut": "active", "dernier_signal_le": recent},
        {"id": "H1-C", "statut": "archivee", "dernier_signal_le": vieux},
        {"id": "H2-A", "statut": "proposee", "dernier_signal_le": vieux},
    ]
    assert [s["hypothese"] for s in analyse.suggestions_archivage(hs, MAINTENANT)] == ["H1-A"]


# ───────────── Dossier ─────────────

def _jeu():
    hypotheses = [
        {"id": "H2-A", "question_id": "Q2", "type": "hypothese", "enonce": "Adoption affaiblie", "statut": "active", "confiance": "plausible", "dernier_signal_le": MAINTENANT.isoformat()},
        {"id": "H2-B", "question_id": "Q2", "type": "hypothese", "enonce": "Échec OMI, UE référence", "statut": "active", "confiance": "plausible", "dernier_signal_le": MAINTENANT.isoformat()},
        {"id": "H9-Z", "question_id": "Q2", "type": "hypothese", "enonce": "En attente", "statut": "proposee", "confiance": "plausible"},
    ]
    indicateurs = [{"id": "H2-A-1", "hypothese_id": "H2-A", "sens": "confirme", "description": "compromis"}]
    sources = {"gcaptain": {"echiquier": "concurrentiel", "fiabilite": "fiable"}, "serper_imo": {"echiquier": "institutionnel", "fiabilite": "fiable"}}
    signaux = [
        {"id": 10, "titre": "Compromise text emerges at ISWG", "resume": "Texte de compromis.", "domaine": "gcaptain.com", "url": "https://gcaptain.com/a", "source_id": "gcaptain", "pertinent": True, "score": 8, "echiquier": "institutionnel", "evenement_id": 1, "reprise_de": None, "hors_radar": False, "collecte_le": "2026-11-12"},
        {"id": 11, "titre": "IMO Secretary-General statement", "resume": "Déclaration.", "domaine": "imo.org", "url": "https://imo.org/b", "source_id": "serper_imo", "pertinent": True, "score": 7, "echiquier": "institutionnel", "evenement_id": 1, "reprise_de": None, "hors_radar": False, "collecte_le": "2026-11-13"},
        {"id": 12, "titre": "Shipowners slam levy", "resume": "Les armateurs critiquent.", "domaine": "splash247.com", "url": "https://splash247.com/c", "source_id": "gcaptain", "pertinent": True, "score": 6, "echiquier": "concurrentiel", "evenement_id": 2, "reprise_de": None, "hors_radar": False, "collecte_le": "2026-11-13"},
        {"id": 13, "titre": "Wind-assist startup raises funds", "resume": "Levée de fonds voile.", "domaine": "offshore-energy.biz", "url": "https://offshore-energy.biz/d", "source_id": "gcaptain", "pertinent": True, "score": 7, "echiquier": "concurrentiel", "evenement_id": 3, "reprise_de": None, "hors_radar": True, "collecte_le": "2026-11-14"},
        {"id": 14, "titre": "Pirates", "domaine": "x.com", "source_id": "gcaptain", "pertinent": False, "score": 0, "collecte_le": "2026-11-14"},
    ]
    liens = [
        {"id": 1, "signal_id": 10, "hypothese_id": "H2-A", "relation": "soutient", "justification": "compromis", "statut": "propose"},
        {"id": 2, "signal_id": 11, "hypothese_id": "H2-A", "relation": "soutient", "justification": "déclaration", "statut": "valide"},
        {"id": 3, "signal_id": 12, "hypothese_id": "H2-A", "relation": "contredit", "justification": "opposition", "statut": "propose"},
        {"id": 4, "signal_id": 12, "hypothese_id": "H2-B", "relation": "soutient", "justification": "opposition", "statut": "rejete"},
    ]
    questions = [{"id": "Q2", "intitule": "Régulation ?"}]
    return hypotheses, indicateurs, signaux, liens, sources, questions


def _dossier():
    h, i, s, l, src, q = _jeu()
    return analyse.construire_dossier(h, i, s, l, src, s, {"H2-A": {"falsificateur": "nouvel ajournement", "angle_mort": "", "requetes": []}}, q, "2026-11-16", MAINTENANT)


def test_dossier():
    d = _dossier()
    assert [s["id"] for s in d["signaux"]][:3] == ["SIG10", "SIG11", "SIG12"]  # rattachés d'abord
    assert "SIG14" not in {s["id"] for s in d["signaux"]}                        # non pertinent exclu
    h2a = next(h for h in d["hypotheses"] if h["id"] == "H2-A")
    assert h2a["preuves"] == {"soutient": ["SIG10", "SIG11"], "contredit": ["SIG12"]}
    assert h2a["corroboration"]["soutient"]["suffisante"] is True               # presse + institution
    assert h2a["corroboration"]["contredit"]["suffisante"] is False
    h2b = next(h for h in d["hypotheses"] if h["id"] == "H2-B")
    assert h2b["preuves"] == {"soutient": [], "contredit": []}                  # lien rejeté ignoré
    assert [h["id"] for h in d["hypotheses_en_attente"]] == ["H9-Z"]
    assert "H9-Z" not in {h["id"] for h in d["hypotheses"]}
    assert d["hors_radar_candidats"] == ["SIG13"]
    assert d["echiquiers_silencieux"] == ["societe_civile"]
    assert h2a["avocat_du_diable"]["falsificateur"] == "nouvel ajournement"


# ───────────── Avocat du diable (D23) ─────────────

def test_avocat_nettoie_et_plafonne_les_requetes():
    brut = [
        {"hypothese": "H1-A", "falsificateur": "f1", "requetes": ['"methanol orders" OR ammonia site:x.com surge', "LNG orders fall"]},
        {"hypothese": "H2-A", "falsificateur": "f2", "requetes": ["IMO vote adjourned again", "x"]},
        {"hypothese": "H9-Z", "falsificateur": "inventée", "requetes": ["a b c"]},
        {"hypothese": "H1-A", "falsificateur": "doublon", "requetes": ["a b"]},
    ]
    r = avocat.valider(brut, {"H1-A", "H2-A"}, max_requetes=2)
    assert set(r) == {"H1-A", "H2-A"} and r["H1-A"]["falsificateur"] == "f1"
    assert r["H1-A"]["requetes"] == ["methanol orders ammonia surge"]     # OR, guillemets et site: retirés
    assert r["H2-A"]["requetes"] == ["IMO vote adjourned again"]          # tourniquet : chacune a sa requête


# ───────────── Brief : contrôle (D25) et bridage (D18) ─────────────

def _brut():
    return {
        "synthese": "Semaine dominée par l'OMI (SIG10). Au S1 2026, le GNL dominait.",
        "mouvements": [
            {
                "titre": "Un compromis se dessine à l'OMI",
                "questions": ["Q2", "Q9"],
                "hypotheses": ["H2-A", "H7-X"],
                "formuler": {"lectures": [{"hypothese": "H2-A", "lecture": "Adoption affaiblie probable (SIG10)"}], "contre_lecture": "Effet d'annonce (SIG999)", "signaux_attendus": ["vote le 4 décembre"]},
                "tester": {
                    "elements": [
                        {"fait": "Texte de compromis", "interpretation": "convergence", "sens": "soutient", "hypothese": "H2-A", "signaux": ["SIG10", "SIG11"]},
                        {"fait": "Inventé", "interpretation": "x", "sens": "soutient", "hypothese": "H2-A", "signaux": ["SIG999"]},
                        {"fait": "Armateurs contre", "interpretation": "résistance", "sens": "contredit", "hypothese": "H2-A", "signaux": ["SIG12"]},
                        {"fait": "Hypothèse inconnue", "interpretation": "x", "sens": "soutient", "hypothese": "H7-X", "signaux": ["SIG10"]},
                    ],
                    "avocat_du_diable": "Pas de nouvel ajournement observé.",
                },
                "tracer": {"incertitudes": ["position américaine"], "a_surveiller": ["vote du 4 décembre"]},
                "vraisemblance": [{"hypothese": "H2-A", "niveau": "Probable", "justification": "ok"}, {"hypothese": "H2-B", "niveau": "certain", "justification": "non"}],
                "suggestions": [{"hypothese": "H2-A", "statut_suggere": "renforcee", "motif": "compromis"}, {"hypothese": "H2-B", "statut_suggere": "affaiblie", "motif": "pas de preuve"}],
            },
            {"titre": "Mouvement sans preuve", "tester": {"elements": [{"fait": "x", "sens": "soutient", "hypothese": "H2-A", "signaux": []}]}},
            {"titre": "M3", "tester": {"elements": [{"fait": "x", "sens": "soutient", "hypothese": "H2-B", "signaux": ["SIG12"]}]}},
            {"titre": "M4 au-delà du plafond", "tester": {"elements": [{"fait": "x", "sens": "soutient", "hypothese": "H2-B", "signaux": ["SIG12"]}]}},
        ],
        "enchainements": [
            {"description": "Position institutionnelle puis réaction des armateurs", "signaux": ["SIG11", "SIG12"]},
            {"description": "Même échiquier", "signaux": ["SIG10", "SIG11"]},
        ],
        "hors_radar": [{"signal": "SIG13", "pourquoi": "voile"}, {"signal": "SIG12", "pourquoi": "pas candidat"}],
    }


def test_controle_du_brief():
    d = _dossier()
    b = brief.valider(_brut(), d)
    assert len(b["mouvements"]) == 2                                   # sans preuve retiré ; plafond de 3 appliqué avant
    m = b["mouvements"][0]
    assert m["questions"] == ["Q2"] and m["hypotheses"] == ["H2-A"]
    assert [e["fait"] for e in m["tester"]["elements"]] == ["Texte de compromis", "Armateurs contre"]
    assert m["formuler"]["contre_lecture"] == "Effet d'annonce ([non sourcé])"
    assert m["vraisemblance"] == [{"hypothese": "H2-A", "niveau": "probable", "justification": "ok"}]
    sug = {s["hypothese"]: s for s in m["suggestions"]}
    assert sug["H2-A"]["statut_suggere"] == "renforcee"               # presse + institution : autorisée
    assert sug["H2-B"]["statut_suggere"] == "maintenir" and "bridée" in sug["H2-B"]["motif"]
    assert [e["signaux"] for e in b["enchainements"]] == [["SIG11", "SIG12"]]
    assert b["hors_radar"] == [{"signal": "SIG13", "pourquoi": "voile"}]
    assert "S1 2026" in b["synthese"]                                  # « S1 » (semestre) intact
    c = b["controle"]
    assert c["elements_retires"] == 3 and c["suggestions_bridees"] == 1 and c["vocabulaire_corrige"] == 1
    assert c["enchainements_retires"] == 1 and c["references_retirees"] >= 2


def test_brief_refuse_une_reponse_non_objet():
    with pytest.raises(ValueError):
        brief.valider([], _dossier())


def test_rendu_markdown_et_mail():
    d = _dossier()
    b = brief.valider(_brut(), d)
    md = brief.en_markdown(b, d, "https://cockpit.example")
    assert md.startswith("# Brief de veille — semaine du 16 novembre 2026")
    for attendu in ("### Formuler", "### Tester", "### Tracer", "**Contre-lecture**", "[gcaptain.com](https://gcaptain.com/a)",
                    "▼ contredit H2-A", "→ *renforcée*", "## Enchaînements entre échiquiers", "## Hors radar",
                    "aucun signal pertinent sur l'échiquier *société civile*", "En attente".lower()[:0], "[Ouvrir le cockpit"):
        assert attendu in md, attendu
    assert "SIG10" not in md                                           # références converties en liens
    msg = mail.construire("a@b.c", "d@e.f", "Sujet", md)
    html = msg.get_payload()[1].get_payload(decode=True).decode()
    assert "<table>" in html and "<h1>" in html


# ───────────── Décisions humaines ─────────────

def test_changer_statut_historise_et_exige_un_motif(base):
    with pytest.raises(decisions.DecisionInvalide):
        decisions.changer_statut(base, "H2-A", "renforcee", "  ")
    with pytest.raises(decisions.DecisionInvalide):
        decisions.changer_statut(base, "H2-A", "renforcee", "x", confiance="certain")
    decisions.changer_statut(base, "H2-A", "renforcee", "Compromis ISWG", confiance="probable")
    h = base.t("hypotheses").select("*").eq("id", "H2-A").execute().data[0]
    assert (h["statut"], h["confiance"]) == ("renforcee", "probable")
    versions = base.t("hypotheses_versions").select("*").eq("hypothese_id", "H2-A").execute().data
    assert [(v["statut"], v["auteur"]) for v in versions] == [("proposee", "agent"), ("active", "humain"), ("renforcee", "humain")]


def test_ajouter_et_reformuler(base):
    h = decisions.ajouter_hypothese(base, "Q1", "hypothese", "L'éthanol devient une troisième voie crédible d'ici 2030.", "peu probable", "Intuition après salon")
    assert h["id"] == "H1-D" and h["statut"] == "active"
    decisions.reformuler(base, "H1-D", "L'éthanol devient une voie crédible pour les vraquiers d'ici 2030.", "Précision du segment")
    assert len(base.t("hypotheses_versions").select("*").eq("hypothese_id", "H1-D").execute().data) == 2


def test_rejet_de_lien_exige_un_motif_structure(base):
    base.t("signaux").insert({"url": "u", "url_norm": "u", "titre": "t"}).execute()
    base.t("liens").insert({"signal_id": 1, "hypothese_id": "H2-A", "relation": "soutient"}).execute()
    with pytest.raises(decisions.DecisionInvalide):
        decisions.statuer_lien(base, 1, "rejete")
    decisions.statuer_lien(base, 1, "rejete", "mauvaise_lecture")
    assert base.t("liens").select("*").execute().data[0]["motif_rejet"] == "mauvaise_lecture"
    assert base.t("feedbacks").select("*").execute().data[0]["motif"] == "mauvaise_lecture"


def test_brief_valide_jamais_ecrase(base):
    assert base.enregistrer_brief("2026-11-16", {"v": 1}, "md1")
    assert base.enregistrer_brief("2026-11-16", {"v": 2}, "md2")
    decisions.valider_brief(base, "2026-11-16")
    assert not base.enregistrer_brief("2026-11-16", {"v": 3}, "md3")
    assert base.brief("2026-11-16")["contenu"] == {"v": 2}


# ───────────── Passage hebdomadaire complet ─────────────

class ClientScenario:
    """Simule le modèle d'analyse : 1er appel = avocat du diable, 2e = brief."""

    def __init__(self):
        self.budget = Budget(3)
        self.messages = []

    def appeler(self, modele, systeme, message, max_tokens=4096):
        self.budget.consommer()
        self.messages.append((systeme, message))
        if systeme.startswith("Tu joues l'avocat du diable"):
            return json.dumps([{"hypothese": "H2-A", "falsificateur": "Nouvel ajournement à l'OMI", "angle_mort": "presse seule", "requetes": ["IMO net-zero vote postponed"]}])
        dossier, _ = json.JSONDecoder().raw_decode(message.split("\n", 1)[1])
        h2a = next(h for h in dossier["hypotheses"] if h["id"] == "H2-A")
        refs = h2a["preuves"]["soutient"] + h2a["preuves"]["contredit"]
        return json.dumps({
            "synthese": "Semaine OMI.",
            "mouvements": [{
                "titre": "OMI : vers un report ?", "questions": ["Q2"], "hypotheses": ["H2-A"],
                "formuler": {"lectures": [{"hypothese": "H2-A", "lecture": "l"}], "contre_lecture": "c", "signaux_attendus": []},
                "tester": {"elements": [{"fait": "f", "interpretation": "i", "sens": "contredit", "hypothese": "H2-A", "signaux": refs}], "avocat_du_diable": "observé"},
                "tracer": {"incertitudes": [], "a_surveiller": []},
                "vraisemblance": [{"hypothese": "H2-A", "niveau": "plausible", "justification": "j"}],
                "suggestions": [{"hypothese": "H2-A", "statut_suggere": "affaiblie", "motif": "report évoqué"}],
            }],
            "enchainements": [], "hors_radar": [],
        })


class TriScenario:
    def __init__(self, cle, budget):
        self.budget = budget

    def appeler(self, modele, systeme, message, max_tokens=4096):
        self.budget.consommer()
        lot = json.loads(message.split("\n", 1)[1])
        return json.dumps([
            {"i": a["i"], "pertinent": True, "score": 8, "echiquier": "institutionnel", "questions": ["Q2"],
             "liens": [{"hypothese": "H2-A", "indicateur": "H2-A-3", "relation": "contredit", "justification": "report du vote"}], "resume": "Report."}
            for a in lot
        ])


def test_passage_hebdomadaire(base, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("SERPER_API_KEY", "x")
    monkeypatch.setattr(run_daily, "ClientLLM", TriScenario)
    requetes = []

    def serper(cle, requete, langue, source_id, origine):
        requetes.append((requete, origine))
        return [
            {"url": "https://gcaptain.com/report", "titre": "IMO net-zero vote postponed amid emissions row", "extrait": "Delegates delay GHG vote.", "source_id": source_id, "origine": origine, "domaine": "gcaptain.com", "langue": "en", "publie_le": None},
            {"url": "https://www.imo.org/en/MediaCentre/x", "titre": "IMO statement on net-zero framework session emissions", "extrait": "The session was adjourned.", "source_id": source_id, "origine": origine, "domaine": "imo.org", "langue": "en", "publie_le": None},
        ]

    monkeypatch.setattr(run_daily, "rechercher_serper", serper)
    envois = []
    client = ClientScenario()
    bilan = run_weekly.executer(base, config.parametres(), client, date(2026, 11, 18), lambda sujet, md: envois.append((sujet, md)))

    assert requetes == [("IMO net-zero vote postponed", "avocat:H2-A")]
    assert len(client.messages) == 2
    dossier = json.loads(client.messages[1][1].split("\n", 1)[1])
    assert dossier["semaine"] == "2026-11-16"
    h2a = next(h for h in dossier["hypotheses"] if h["id"] == "H2-A")
    assert h2a["avocat_du_diable"]["falsificateur"] == "Nouvel ajournement à l'OMI"
    assert h2a["corroboration"]["contredit"]["suffisante"] is True     # presse + institution trouvées par l'avocat
    b = bilan["brief"]
    assert b["mouvements"][0]["suggestions"][0]["statut_suggere"] == "affaiblie"
    stocke = base.brief("2026-11-16")
    assert stocke["statut"] == "brouillon" and stocke["contenu"]["mouvements"]
    assert envois and envois[0][0] == "Brief de veille — semaine du 16 novembre 2026"
    # L'agent n'a modifié aucun statut : seules les versions de l'import et de l'activation existent.
    assert all(v["auteur"] == "agent" or v["motif"] == "test" for v in base.t("hypotheses_versions").select("*").execute().data)
    assert {h["statut"] for h in base.t("hypotheses").select("*").execute().data} == {"active"}


def test_sans_hypothese_active_pas_de_brief(base, monkeypatch):
    for h in base.t("hypotheses").select("*").execute().data:
        decisions.changer_statut(base, h["id"], "archivee", "fin")
    client = ClientScenario()
    bilan = run_weekly.executer(base, config.parametres(), client, date(2026, 11, 16), None)
    assert bilan["brief"] is None and client.messages == [] and "Aucune hypothèse active" in bilan["erreurs"][0]


def test_brief_inexploitable_puis_reussi_a_la_seconde_tentative(base, monkeypatch):
    monkeypatch.setattr(run_daily, "rechercher_serper", lambda *a: [])
    monkeypatch.setenv("SERPER_API_KEY", "x")

    class Bavard(ClientScenario):
        essais = 0

        def appeler(self, modele, systeme, message, max_tokens=4096):
            if systeme.startswith("Tu rédiges") and Bavard.essais == 0:
                Bavard.essais += 1
                self.budget.consommer()
                self.dernier = {"stop_reason": "end_turn", "blocs": ["text"], "tokens_sortie": 12, "debut": "Voici mon analyse", "fin": "fin"}
                return "Voici mon analyse en prose, sans JSON."
            return super().appeler(modele, systeme, message, max_tokens)

    erreurs = []
    client = Bavard()
    bilan = run_weekly.executer(base, config.parametres(), client, date(2026, 11, 16), None, erreurs)
    assert "RAPPEL" in client.messages[-1][1]
    assert any("tentative 1 inexploitable" in e and "end_turn" in e for e in erreurs)
    assert bilan["brief"] is not None


def test_brief_deux_fois_inexploitable_remonte_le_diagnostic(base, monkeypatch):
    monkeypatch.setattr(run_daily, "rechercher_serper", lambda *a: [])
    monkeypatch.setenv("SERPER_API_KEY", "x")

    class Muet(ClientScenario):
        def appeler(self, modele, systeme, message, max_tokens=4096):
            if systeme.startswith("Tu rédiges"):
                self.budget.consommer()
                self.dernier = {"stop_reason": "max_tokens", "blocs": ["thinking"], "tokens_sortie": 12000, "debut": "", "fin": ""}
                return ""
            return super().appeler(modele, systeme, message, max_tokens)

    erreurs = []
    with pytest.raises(ValueError, match="deux tentatives"):
        run_weekly.executer(base, config.parametres(), Muet(), date(2026, 11, 16), None, erreurs)
    brief_ko = [e for e in erreurs if e.startswith("Brief, tentative")]
    assert len(brief_ko) == 2 and "max_tokens" in brief_ko[0] and "thinking" in brief_ko[0]
