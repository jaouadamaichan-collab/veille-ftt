"""Accès Supabase. Toutes les écritures passent par ce module."""

from __future__ import annotations

from datetime import datetime, timezone

from .collect import SEUIL_DESACTIVATION


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base:
    def __init__(self, url: str, cle: str):
        from supabase import create_client

        if not url or not cle:
            raise RuntimeError("SUPABASE_URL et SUPABASE_SERVICE_KEY sont requis")
        self.c = create_client(url, cle)

    def t(self, nom: str):
        return self.c.table(nom)

    # ───────────── Journal d'exécution ─────────────

    def debut_run(self, type_run: str) -> int:
        return self.t("runs").insert({"type": type_run}).execute().data[0]["id"]

    def fin_run(self, run_id: int, statut: str, stats: dict, erreurs: list[str]) -> None:
        self.t("runs").update({"fin": maintenant(), "statut": statut, "erreurs": erreurs[:50], **stats}).eq("id", run_id).execute()

    # ───────────── Référentiels ─────────────

    def upsert(self, table: str, lignes: list[dict], ecraser: bool = False) -> None:
        if lignes:
            self.t(table).upsert(lignes, on_conflict="id", ignore_duplicates=not ecraser).execute()

    def ids_existants(self, table: str) -> set[str]:
        return {r["id"] for r in self.t(table).select("id").execute().data}

    def sources_actives(self) -> list[dict]:
        return self.t("sources").select("*").eq("actif", True).execute().data

    def sante_source(self, source: dict, ok: bool, erreur: str | None = None) -> None:
        if ok:
            maj = {"derniere_reussite": maintenant(), "echecs_consecutifs": 0, "derniere_erreur": None, "verifie": True}
        else:
            echecs = (source.get("echecs_consecutifs") or 0) + 1
            maj = {"echecs_consecutifs": echecs, "derniere_erreur": (erreur or "")[:500]}
            if echecs >= SEUIL_DESACTIVATION:
                maj["actif"] = False
        self.t("sources").update(maj).eq("id", source["id"]).execute()

    def hypotheses_ouvertes(self) -> list[dict]:
        return self.t("hypotheses").select("*").neq("statut", "archivee").order("id").execute().data

    def indicateurs_actifs(self, ids_hypotheses: list[str]) -> list[dict]:
        if not ids_hypotheses:
            return []
        return (
            self.t("indicateurs").select("*").eq("actif", True).in_("hypothese_id", ids_hypotheses).order("id").execute().data
        )

    # ───────────── Signaux ─────────────

    def urls_connues(self, urls_norm: list[str]) -> set[str]:
        connues: set[str] = set()
        for k in range(0, len(urls_norm), 100):
            morceau = urls_norm[k : k + 100]
            connues |= {r["url_norm"] for r in self.t("signaux").select("url_norm").in_("url_norm", morceau).execute().data}
        return connues

    def signaux_recents(self, depuis: str) -> list[dict]:
        return (
            self.t("signaux")
            .select("id, evenement_id, reprise_de, titre, extrait, domaine")
            .gte("collecte_le", depuis)
            .order("id")
            .limit(5000)
            .execute()
            .data
        )

    def creer_evenement(self, titre: str) -> int:
        return self.t("evenements").insert({"titre_ref": titre[:300]}).execute().data[0]["id"]

    def evenement_vu(self, evenement_id: int) -> None:
        self.t("evenements").update({"dernier_vu": maintenant()}).eq("id", evenement_id).execute()

    def inserer_signal(self, signal: dict) -> int:
        return self.t("signaux").insert(signal).execute().data[0]["id"]

    def signaux_a_trier(self, limite: int) -> list[dict]:
        return (
            self.t("signaux")
            .select("id, titre, extrait, domaine, publie_le, collecte_le, source_id")
            .eq("trie", False)
            .order("id")
            .limit(limite)
            .execute()
            .data
        )

    def enregistrer_tri(self, resultat: dict) -> None:
        champs = {k: resultat[k] for k in ("trie", "pertinent", "score", "echiquier", "questions", "resume", "hors_radar", "triage_brut") if k in resultat}
        self.t("signaux").update(champs).eq("id", resultat["signal_id"]).execute()

    def inserer_liens(self, liens: list[dict]) -> None:
        if liens:
            self.t("liens").upsert(liens, on_conflict="signal_id,hypothese_id", ignore_duplicates=True).execute()

    def hypotheses_signalees(self, ids: set[str]) -> None:
        if ids:
            self.t("hypotheses").update({"dernier_signal_le": maintenant()}).in_("id", sorted(ids)).execute()
