"""Test d'intégration de run_daily avec une base, des flux et un LLM simulés."""

import json

from veille import config, run_daily
from veille.collect import ErreurSource


class Requete:
    def __init__(self, data):
        self.data = data

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def execute(self):
        return self


class FausseBase:
    def __init__(self):
        self.sources = [
            {"id": "gcaptain", "type": "rss", "echiquier": "concurrentiel", "langue": "en", "url": "u", "echecs_consecutifs": 0},
            {"id": "mort", "type": "rss", "echiquier": "societe_civile", "langue": "en", "url": "u2", "echecs_consecutifs": 4},
            {"id": "serper_imo", "type": "serper", "echiquier": "institutionnel", "langue": "en", "requete": "q imo"},
            {"id": "serper_indicateurs", "type": "serper", "echiquier": "concurrentiel", "langue": "en", "requete": None},
        ]
        self.signaux, self.liens, self.evenements, self.sante = [], [], 0, {}
        self.signalees = set()

    def t(self, nom):
        return Requete([{"id": s["id"], "echiquier": s["echiquier"]} for s in self.sources])

    def sources_actives(self):
        return self.sources

    def sante_source(self, s, ok, erreur=None):
        self.sante[s["id"]] = ok

    def urls_connues(self, urls):
        return {s["url_norm"] for s in self.signaux}

    def signaux_recents(self, depuis):
        return [dict(s) for s in self.signaux]

    def creer_evenement(self, titre):
        self.evenements += 1
        return self.evenements

    def evenement_vu(self, i):
        pass

    def inserer_signal(self, s):
        s = {**s, "id": len(self.signaux) + 1, "trie": False}
        self.signaux.append(s)
        return s["id"]

    def signaux_a_trier(self, limite):
        return [s for s in self.signaux if not s["trie"]][:limite]

    def enregistrer_tri(self, r):
        s = next(s for s in self.signaux if s["id"] == r["signal_id"])
        s.update({k: v for k, v in r.items() if k not in ("signal_id", "liens")})

    def inserer_liens(self, liens):
        self.liens += liens

    def hypotheses_signalees(self, ids):
        self.signalees |= ids


def faux_rss(source, depuis):
    if source["id"] == "mort":
        raise ErreurSource("404")
    return [
        {"url": "https://gcaptain.com/a?utm_source=x", "titre": "IMO net-zero framework talks stall again", "extrait": "Delegates failed to agree on GHG pricing.", "source_id": "gcaptain", "origine": "rss", "domaine": "gcaptain.com", "langue": "en", "publie_le": None},
        {"url": "https://gcaptain.com/b", "titre": "Pirates attack tanker off Somalia", "extrait": "", "source_id": "gcaptain", "origine": "rss", "domaine": "gcaptain.com", "langue": "en", "publie_le": None},
    ]


def faux_serper(cle, requete, langue, source_id, origine):
    return [
        {"url": "https://gcaptain.com/a", "titre": "IMO net-zero framework talks stall again", "extrait": "", "source_id": source_id, "origine": origine, "domaine": "gcaptain.com", "langue": "en", "publie_le": None},
        {"url": "https://splash247.com/x", "titre": "Methanol dual-fuel orders collapse as owners pick LNG", "extrait": "Only four methanol ships ordered.", "source_id": source_id, "origine": origine, "domaine": "splash247.com", "langue": "en", "publie_le": None},
    ]


class FauxClient:
    appels = []

    def __init__(self, cle, budget):
        self.budget = budget

    def appeler(self, modele, systeme, message, max_tokens=4096):
        self.budget.consommer()
        lot = json.loads(message.split("\n", 1)[1])
        FauxClient.appels.append(lot)
        sortie = []
        for a in lot:
            if "Methanol" in a["titre"]:
                sortie.append({"i": a["i"], "pertinent": True, "score": 8, "echiquier": "concurrentiel", "questions": ["Q1"],
                               "liens": [{"hypothese": "H1-A", "indicateur": "H1-A-1", "relation": "soutient", "justification": "4 navires méthanol seulement"},
                                         {"hypothese": "H1-B", "indicateur": None, "relation": "contredit", "justification": "commandes méthanol effondrées"}],
                               "resume": "Effondrement des commandes méthanol."})
            else:
                sortie.append({"i": a["i"], "pertinent": True, "score": 6, "echiquier": "institutionnel", "questions": ["Q2"], "liens": [], "resume": "Blocage à l'OMI."})
        return "```json\n" + json.dumps(sortie) + "\n```"


def test_chaine_complete(monkeypatch):
    monkeypatch.setattr(run_daily, "collecter_rss", faux_rss)
    monkeypatch.setattr(run_daily, "rechercher_serper", faux_serper)
    monkeypatch.setattr(run_daily, "ClientLLM", FauxClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("SERPER_API_KEY", "x")
    p = config.parametres()
    db = FausseBase()
    stats = {"nb_collectes": 0, "nb_nouveaux": 0, "nb_tries": 0, "nb_appels_llm": 0, "nb_requetes_serper": 0}
    erreurs = []
    hypotheses = [{**h, "question_id": h["question"]} for h in config.hypotheses()]
    indicateurs = [{**i, "hypothese_id": h["id"]} for h in config.hypotheses() for i in h["indicateurs"]]

    items = run_daily.collecter(db, p, stats, erreurs, indicateurs)
    run_daily.inserer(db, p, items, stats)
    run_daily.trier(db, p, hypotheses, indicateurs, stats, erreurs)

    # Santé des sources
    assert db.sante == {"gcaptain": True, "mort": False}
    assert any("mort" in e for e in erreurs)
    # Dédoublonnage : gcaptain.com/a (RSS avec utm) et gcaptain.com/a (Serper) ne font qu'un
    urls = sorted(s["url_norm"] for s in db.signaux)
    assert urls == ["https://gcaptain.com/a", "https://gcaptain.com/b", "https://splash247.com/x"]
    # Pré-filtre : les pirates sont écartés sans appel LLM
    pirates = next(s for s in db.signaux if "Pirates" in s["titre"])
    assert pirates["trie"] and pirates["pertinent"] is False
    assert all("Pirates" not in a["titre"] for lot in FauxClient.appels for a in lot)
    # Tri et liens proposés (contre-preuve comprise)
    assert {(l["hypothese_id"], l["relation"]) for l in db.liens} == {("H1-A", "soutient"), ("H1-B", "contredit")}
    assert db.signalees == {"H1-A", "H1-B"}
    imo = next(s for s in db.signaux if "IMO" in s["titre"])
    assert imo["hors_radar"] is True and imo["echiquier"] == "institutionnel"
    assert stats["nb_appels_llm"] == 1 and stats["nb_tries"] == 3
