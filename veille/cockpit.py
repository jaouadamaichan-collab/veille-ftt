"""Cockpit de l'analyste (D9) : c'est ici que l'humain tranche (D5, D19).

Toute action passe par veille.decisions, qui historise. Le point d'entrée Streamlit est cockpit/app.py.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import streamlit as st

from . import decisions
from .brief import NOMS_ECHIQUIERS, NOMS_STATUTS, date_longue
from .config import FIABILITES, VRAISEMBLANCE
from .db import Base

PAGES = ("Brief de la semaine", "Hypothèses", "Liens à statuer", "Sources", "Journal")
NOMS_STATUTS_H = {"proposee": "proposée", "active": "active", "renforcee": "renforcée", "affaiblie": "affaiblie", "archivee": "archivée"}
COULEURS_STATUTS = {"proposee": "gray", "active": "blue", "renforcee": "green", "affaiblie": "orange", "archivee": "gray"}
NOMS_MOTIFS = {"pas_nouveau": "Pas nouveau", "pas_source": "Pas sourcé", "hors_sujet": "Hors sujet", "mauvaise_lecture": "Mauvaise lecture"}
NOMS_FIABILITE = {"fiable": "fiable", "a_confirmer": "à confirmer", "douteuse": "douteuse"}

CSS = """
<style>
.bloc-h{border:1px solid rgba(128,128,128,.25);border-radius:.6rem;padding:.8rem 1rem;margin-bottom:.6rem}
.petit{font-size:.82rem;opacity:.75}
</style>
"""


def jour(iso) -> str:
    return str(iso or "")[:16].replace("T", " ")


def statut_badge(statut: str) -> str:
    return f":{COULEURS_STATUTS.get(statut, 'gray')}-badge[{NOMS_STATUTS_H.get(statut, statut)}]"


def notifier(message: str) -> None:
    st.session_state["_notification"] = message


def afficher_notification() -> None:
    message = st.session_state.pop("_notification", None)
    if message:
        st.success(message)


# ───────────── Brief ─────────────

def page_brief(db: Base) -> None:
    briefs = db.t("briefs").select("semaine, statut").order("semaine", desc=True).limit(20).execute().data
    if not briefs:
        st.info("Aucun brief pour l'instant. Le premier sera produit lundi matin (ou via *Actions → Brief hebdomadaire → Run workflow*).")
        return
    semaine = st.selectbox(
        "Semaine",
        [b["semaine"] for b in briefs],
        format_func=lambda s: f"Semaine du {date_longue(s)}" + (" · validé" if next(b for b in briefs if b["semaine"] == s)["statut"] == "valide" else ""),
    )
    b = db.brief(semaine)
    contenu = b["contenu"]
    hypotheses = {h["id"]: h for h in db.t("hypotheses").select("*").execute().data}

    onglet_brief, onglet_decisions = st.tabs(["Lecture", "Décisions à prendre"])
    with onglet_brief:
        st.markdown(b["markdown"] or "")

    with onglet_decisions:
        suggestions = [
            (n, s) for n, m in enumerate(contenu.get("mouvements", []), 1) for s in m.get("suggestions", []) if s["statut_suggere"] != "maintenir"
        ]
        archivages = contenu.get("suggestions_archivage", [])
        if not suggestions and not archivages:
            st.caption("Aucune suggestion de changement de statut cette semaine.")
        for n, s in suggestions:
            h = hypotheses.get(s["hypothese"])
            if not h:
                continue
            with st.container(border=True):
                st.markdown(f"**{h['id']}** {statut_badge(h['statut'])} → suggestion : **{NOMS_STATUTS[s['statut_suggere']]}** *(mouvement {n})*")
                st.caption(h["enonce"])
                st.write(s["motif"])
                if h["statut"] == s["statut_suggere"]:
                    st.caption("Déjà appliquée.")
                    continue
                with st.form(f"sug-{semaine}-{n}-{h['id']}"):
                    motif = st.text_input("Motif de la décision", value=f"Brief du {semaine} : {s['motif'][:200]}")
                    confiance = st.selectbox("Vraisemblance", VRAISEMBLANCE, index=VRAISEMBLANCE.index(h["confiance"]) if h.get("confiance") in VRAISEMBLANCE else 1)
                    if st.form_submit_button(f"Appliquer : {NOMS_STATUTS[s['statut_suggere']]}", type="primary"):
                        decisions.changer_statut(db, h["id"], s["statut_suggere"], motif, confiance)
                        notifier(f"{h['id']} passée en « {NOMS_STATUTS_H[s['statut_suggere']]} ».")
                        st.rerun()
        for a in archivages:
            h = hypotheses.get(a["hypothese"])
            if not h or h["statut"] == "archivee":
                continue
            with st.container(border=True):
                st.markdown(f"**{h['id']}** {statut_badge(h['statut'])} → suggestion : **archiver**")
                st.caption(f"{a['motif']} (dernier signal : {a['depuis']}). {h['enonce']}")
                if st.button(f"Archiver {h['id']}", key=f"arch-{semaine}-{h['id']}"):
                    decisions.changer_statut(db, h["id"], "archivee", f"Brief du {semaine} : {a['motif']}")
                    notifier(f"{h['id']} archivée.")
                    st.rerun()

        st.divider()
        st.markdown("**Retour sur les mouvements**")
        for n, m in enumerate(contenu.get("mouvements", []), 1):
            with st.form(f"fb-{semaine}-{n}"):
                st.markdown(f"{n}. {m['titre']}")
                c1, c2 = st.columns(2)
                verdict = c1.radio("Utilité", ["utile", "partiel", "rejete"], horizontal=True, format_func={"utile": "Utile", "partiel": "Partiel", "rejete": "Rejeté"}.get)
                motif = c2.selectbox("Motif (si partiel ou rejeté)", [None, *decisions.MOTIFS_REJET], format_func=lambda x: "—" if x is None else NOMS_MOTIFS[x])
                if st.form_submit_button("Enregistrer"):
                    db.t("feedbacks").insert({"cible_type": "mouvement", "cible_id": f"{semaine}#{n}", "verdict": verdict, "motif": motif if verdict != "utile" else None}).execute()
                    notifier("Retour enregistré.")
                    st.rerun()

        st.divider()
        if b["statut"] == "valide":
            st.success("Brief validé : il ne sera plus régénéré.")
        elif st.button("Valider ce brief", type="primary", key=f"valider-{semaine}"):
            decisions.valider_brief(db, semaine)
            notifier("Brief validé.")
            st.rerun()


# ───────────── Hypothèses ─────────────

def page_hypotheses(db: Base) -> None:
    hypotheses = db.t("hypotheses").select("*").order("id").execute().data
    questions = db.t("questions").select("*").order("id").execute().data
    indicateurs = db.t("indicateurs").select("*").order("id").execute().data
    depuis = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    liens = db.t("liens").select("*").gte("cree_le", depuis).execute().data
    compte = Counter((l["hypothese_id"], l["relation"]) for l in liens if l["statut"] != "rejete")

    voir_archivees = st.toggle("Afficher les hypothèses archivées", value=False)
    for q in questions:
        st.subheader(f"{q['id']} — {q['intitule']}")
        for h in (h for h in hypotheses if h["question_id"] == q["id"]):
            if h["statut"] == "archivee" and not voir_archivees:
                continue
            etiquette = "contre-hypothèse" if h["type"] == "contre" else "hypothèse"
            titre = f"{h['id']} · {NOMS_STATUTS_H[h['statut']]} · {h.get('confiance') or '—'} · ▲{compte[(h['id'], 'soutient')]} ▼{compte[(h['id'], 'contredit')]}"
            with st.expander(titre):
                st.markdown(f"{statut_badge(h['statut'])} *{etiquette}* — vraisemblance **{h.get('confiance') or '—'}**")
                st.write(h["enonce"])
                if h.get("contexte"):
                    st.caption(f"Contexte initial : {h['contexte']}")
                st.caption(f"30 derniers jours : {compte[(h['id'], 'soutient')]} lien(s) qui soutiennent, {compte[(h['id'], 'contredit')]} qui contredisent · dernier signal : {jour(h.get('dernier_signal_le')) or '—'}")
                inds = [i for i in indicateurs if i["hypothese_id"] == h["id"]]
                if inds:
                    st.markdown("**Indicateurs**")
                    for i in inds:
                        st.markdown(f"- `{i['id']}` {'▲' if i['sens'] == 'confirme' else '▼'} {i['description']}")

                c1, c2 = st.columns(2)
                with c1.form(f"statut-{h['id']}"):
                    st.markdown("**Changer le statut**")
                    statut = st.selectbox("Statut", decisions.STATUTS, index=decisions.STATUTS.index(h["statut"]), format_func=NOMS_STATUTS_H.get)
                    confiance = st.selectbox("Vraisemblance", VRAISEMBLANCE, index=VRAISEMBLANCE.index(h["confiance"]) if h.get("confiance") in VRAISEMBLANCE else 1)
                    motif = st.text_input("Motif (obligatoire)")
                    if st.form_submit_button("Enregistrer"):
                        try:
                            decisions.changer_statut(db, h["id"], statut, motif, confiance)
                            notifier(f"{h['id']} mise à jour.")
                            st.rerun()
                        except decisions.DecisionInvalide as ex:
                            st.error(str(ex))
                with c2.form(f"enonce-{h['id']}"):
                    st.markdown("**Reformuler**")
                    enonce = st.text_area("Énoncé", value=h["enonce"], height=110)
                    motif_r = st.text_input("Motif de la reformulation (obligatoire)")
                    if st.form_submit_button("Reformuler"):
                        try:
                            decisions.reformuler(db, h["id"], enonce, motif_r)
                            notifier(f"{h['id']} reformulée.")
                            st.rerun()
                        except decisions.DecisionInvalide as ex:
                            st.error(str(ex))

                versions = db.t("hypotheses_versions").select("*").eq("hypothese_id", h["id"]).order("cree_le", desc=True).execute().data
                if versions:
                    st.markdown("**Historique**")
                    st.dataframe(
                        [{"Date": jour(v["cree_le"]), "Statut": NOMS_STATUTS_H.get(v["statut"], v["statut"]), "Vraisemblance": v.get("confiance"), "Auteur": v["auteur"], "Motif": v.get("motif")} for v in versions],
                        hide_index=True,
                        use_container_width=True,
                    )

    st.divider()
    with st.form("nouvelle-hypothese"):
        st.markdown("**Ajouter une hypothèse**")
        c1, c2, c3 = st.columns(3)
        q = c1.selectbox("Question", [q["id"] for q in questions])
        type_h = c2.selectbox("Type", ["hypothese", "contre"], format_func={"hypothese": "hypothèse", "contre": "contre-hypothèse"}.get)
        confiance = c3.selectbox("Vraisemblance", VRAISEMBLANCE, index=1)
        enonce = st.text_area("Énoncé")
        motif = st.text_input("Pourquoi cette hypothèse ?")
        if st.form_submit_button("Ajouter"):
            try:
                h = decisions.ajouter_hypothese(db, q, type_h, enonce, confiance, motif)
                notifier(f"{h['id']} ajoutée. Pensez à lui donner des indicateurs (fichier config ou prochaine version du cockpit).")
                st.rerun()
            except decisions.DecisionInvalide as ex:
                st.error(str(ex))


# ───────────── Liens ─────────────

def page_liens(db: Base) -> None:
    hypotheses = db.t("hypotheses").select("id, enonce, statut").neq("statut", "archivee").order("id").execute().data
    filtre = st.selectbox("Hypothèse", ["Toutes", *[h["id"] for h in hypotheses]])
    q = db.t("liens").select("*").eq("statut", "propose")
    if filtre != "Toutes":
        q = q.eq("hypothese_id", filtre)
    liens = q.order("id", desc=True).limit(40).execute().data
    if not liens:
        st.info("Aucun lien en attente.")
        return
    st.caption(f"{len(liens)} lien(s) proposé(s) par l'agent, les plus récents d'abord. Validez ce qui est juste, rejetez le reste avec un motif : c'est ce qui calibre l'agent.")
    signaux = {s["id"]: s for s in db.t("signaux").select("*").in_("id", sorted({l["signal_id"] for l in liens})).execute().data}
    for l in liens:
        s = signaux.get(l["signal_id"])
        if not s:
            continue
        with st.container(border=True):
            fleche = "▲ soutient" if l["relation"] == "soutient" else "▼ contredit"
            st.markdown(f"**{fleche} {l['hypothese_id']}**" + (f" · indicateur `{l['indicateur_id']}`" if l.get("indicateur_id") else ""))
            st.markdown(f"[{s['titre']}]({s['url']}) — *{s.get('domaine')}* · {NOMS_ECHIQUIERS.get(s.get('echiquier'), '—')} · {jour(s.get('publie_le') or s.get('collecte_le'))[:10]}")
            st.write(l.get("justification") or "")
            c1, c2, c3 = st.columns([1, 2, 1])
            if c1.button("Valider", key=f"ok-{l['id']}", type="primary"):
                decisions.statuer_lien(db, l["id"], "valide")
                notifier("Lien validé.")
                st.rerun()
            motif = c2.selectbox("Motif du rejet", decisions.MOTIFS_REJET, key=f"motif-{l['id']}", format_func=NOMS_MOTIFS.get, label_visibility="collapsed")
            if c3.button("Rejeter", key=f"ko-{l['id']}"):
                decisions.statuer_lien(db, l["id"], "rejete", motif)
                notifier("Lien rejeté.")
                st.rerun()


# ───────────── Sources ─────────────

def page_sources(db: Base) -> None:
    sources = db.t("sources").select("*").order("id").execute().data
    st.caption("Réglez la fiabilité (elle pondère les preuves : une source « douteuse » ne compte pas pour la corroboration) et activez ou désactivez les sources.")
    lignes = [
        {
            "id": s["id"],
            "Source": s["nom"],
            "Type": s["type"],
            "Échiquier": NOMS_ECHIQUIERS.get(s["echiquier"], s["echiquier"]),
            "Fiabilité": s["fiabilite"],
            "Active": s["actif"],
            "Échecs": s.get("echecs_consecutifs") or 0,
            "Dernier succès": jour(s.get("derniere_reussite")),
            "Dernière erreur": s.get("derniere_erreur") or "",
        }
        for s in sources
    ]
    modifie = st.data_editor(
        lignes,
        hide_index=True,
        use_container_width=True,
        disabled=["id", "Source", "Type", "Échiquier", "Échecs", "Dernier succès", "Dernière erreur"],
        column_config={
            "id": None,
            "Fiabilité": st.column_config.SelectboxColumn(options=list(FIABILITES), required=True),
            "Active": st.column_config.CheckboxColumn(),
        },
        key="editeur-sources",
    )
    if st.button("Enregistrer les sources", type="primary"):
        n = 0
        for avant, apres in zip(lignes, modifie):
            if (avant["Fiabilité"], avant["Active"]) != (apres["Fiabilité"], apres["Active"]):
                decisions.regler_source(db, avant["id"], fiabilite=apres["Fiabilité"], actif=apres["Active"])
                n += 1
        notifier(f"{n} source(s) mise(s) à jour.")
        st.rerun()


# ───────────── Journal ─────────────

def page_journal(db: Base) -> None:
    runs = db.t("runs").select("*").order("id", desc=True).limit(30).execute().data
    st.dataframe(
        [
            {
                "Début": jour(r["debut"]),
                "Type": r["type"],
                "Statut": r["statut"],
                "Collectés": r.get("nb_collectes"),
                "Nouveaux": r.get("nb_nouveaux"),
                "Triés": r.get("nb_tries"),
                "Appels IA": r.get("nb_appels_llm"),
                "Serper": r.get("nb_requetes_serper"),
                "Incidents": len(r.get("erreurs") or []),
            }
            for r in runs
        ],
        hide_index=True,
        use_container_width=True,
    )
    for r in runs[:5]:
        if r.get("erreurs"):
            with st.expander(f"Incidents du {jour(r['debut'])} ({r['type']})"):
                for e in r["erreurs"]:
                    st.write(f"- {e}")


# ───────────── Application ─────────────

def afficher(db: Base) -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.markdown("## Veille F-T-T")
        st.caption("Décarbonation du transport maritime")
        page = st.radio("Navigation", PAGES, label_visibility="collapsed")
        en_attente = len(db.t("liens").select("id").eq("statut", "propose").execute().data)
        proposees = len(db.t("hypotheses").select("id").eq("statut", "proposee").execute().data)
        st.divider()
        st.metric("Liens à statuer", en_attente)
        if proposees:
            st.metric("Hypothèses à valider", proposees)
    st.title(page)
    afficher_notification()
    {
        "Brief de la semaine": page_brief,
        "Hypothèses": page_hypotheses,
        "Liens à statuer": page_liens,
        "Sources": page_sources,
        "Journal": page_journal,
    }[page](db)
