"""Client Supabase en mémoire, limité aux opérations utilisées par le projet.

Reproduit les comportements qui comptent : identifiants auto-incrémentés, valeurs par défaut
utiles, unicité (url_norm, couple signal/hypothèse), upsert avec ou sans écrasement.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

AUTO_ID = {"runs", "evenements", "signaux", "liens", "hypotheses_versions", "briefs", "feedbacks"}
UNIQUES = {"signaux": [("url_norm",)], "liens": [("signal_id", "hypothese_id")], "briefs": [("semaine",)]}
DEFAUTS = {
    "signaux": {"trie": False, "hors_radar": False, "questions": [], "reprise_de": None, "pertinent": None, "score": None, "echiquier": None, "resume": None},
    "liens": {"statut": "propose", "motif_rejet": None, "indicateur_id": None},
    "hypotheses": {"statut": "proposee", "dernier_signal_le": None, "contexte": None},
    "sources": {"actif": True, "verifie": False, "echecs_consecutifs": 0, "derniere_reussite": None, "derniere_erreur": None},
    "indicateurs": {"actif": True, "dernier_declenchement": None},
    "briefs": {"statut": "brouillon", "markdown": None},
    "runs": {"statut": "en_cours", "erreurs": []},
}
HORODATAGE = {"signaux": "collecte_le", "liens": "cree_le", "hypotheses_versions": "cree_le", "runs": "debut", "briefs": "cree_le", "feedbacks": "cree_le", "evenements": "premier_vu", "hypotheses": "cree_le"}


class ErreurUnicite(Exception):
    pass


class Reponse:
    def __init__(self, data):
        self.data = data


class Requete:
    def __init__(self, base: "FauxSupabase", table: str):
        self.base, self.table = base, table
        self.filtres = []
        self.tri = None
        self.limite = None
        self.operation = ("select", None)

    # ── construction ──
    def select(self, *_):
        self.operation = ("select", None)
        return self

    def insert(self, lignes):
        self.operation = ("insert", lignes)
        return self

    def update(self, valeurs):
        self.operation = ("update", valeurs)
        return self

    def upsert(self, lignes, on_conflict="id", ignore_duplicates=False):
        self.operation = ("upsert", (lignes, on_conflict, ignore_duplicates))
        return self

    def delete(self):
        self.operation = ("delete", None)
        return self

    def eq(self, c, v):
        self.filtres.append(lambda r: r.get(c) == v)
        return self

    def neq(self, c, v):
        self.filtres.append(lambda r: r.get(c) != v)
        return self

    def in_(self, c, vs):
        vs = list(vs)
        self.filtres.append(lambda r: r.get(c) in vs)
        return self

    def gte(self, c, v):
        self.filtres.append(lambda r: r.get(c) is not None and str(r.get(c)) >= str(v))
        return self

    def lte(self, c, v):
        self.filtres.append(lambda r: r.get(c) is not None and str(r.get(c)) <= str(v))
        return self

    def order(self, c, desc=False):
        self.tri = (c, desc)
        return self

    def limit(self, n):
        self.limite = n
        return self

    # ── exécution ──
    def _selection(self):
        lignes = [r for r in self.base.tables.setdefault(self.table, []) if all(f(r) for f in self.filtres)]
        if self.tri:
            c, desc = self.tri
            lignes.sort(key=lambda r: (r.get(c) is None, r.get(c)), reverse=desc)
        return lignes[: self.limite] if self.limite else lignes

    def _inserer(self, ligne):
        table = self.base.tables.setdefault(self.table, [])
        ligne = {**DEFAUTS.get(self.table, {}), **copy.deepcopy(ligne)}
        if self.table in HORODATAGE:
            ligne.setdefault(HORODATAGE[self.table], self.base.horloge())
        if self.table in AUTO_ID and "id" not in ligne:
            self.base.compteurs[self.table] = self.base.compteurs.get(self.table, 0) + 1
            ligne["id"] = self.base.compteurs[self.table]
        for cles in UNIQUES.get(self.table, []) + [("id",)]:
            if any(all(r.get(k) == ligne.get(k) for k in cles) for r in table):
                raise ErreurUnicite(f"{self.table} : doublon sur {cles}")
        table.append(ligne)
        return ligne

    def execute(self):
        op, arg = self.operation
        if op == "select":
            return Reponse(copy.deepcopy(self._selection()))
        if op == "insert":
            lignes = arg if isinstance(arg, list) else [arg]
            return Reponse([copy.deepcopy(self._inserer(l)) for l in lignes])
        if op == "update":
            touchees = self._selection()
            for r in touchees:
                r.update(copy.deepcopy(arg))
            return Reponse(copy.deepcopy(touchees))
        if op == "delete":
            touchees = self._selection()
            self.base.tables[self.table] = [r for r in self.base.tables[self.table] if r not in touchees]
            return Reponse(touchees)
        if op == "upsert":
            lignes, on_conflict, ignorer = arg
            cles = tuple(k.strip() for k in on_conflict.split(","))
            sortie = []
            for l in lignes if isinstance(lignes, list) else [lignes]:
                existante = next((r for r in self.base.tables.setdefault(self.table, []) if all(r.get(k) == l.get(k) for k in cles)), None)
                if existante is None:
                    sortie.append(self._inserer(l))
                elif not ignorer:
                    existante.update(copy.deepcopy(l))
                    sortie.append(existante)
            return Reponse(copy.deepcopy(sortie))
        raise NotImplementedError(op)


class FauxSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.compteurs: dict[str, int] = {}
        self.maintenant = None  # figer l'horloge si besoin

    def horloge(self):
        return self.maintenant or datetime.now(timezone.utc).isoformat()

    def table(self, nom):
        return Requete(self, nom)
