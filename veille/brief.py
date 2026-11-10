"""Brief hebdomadaire F-T-T (D21) : génération par le modèle d'analyse, puis contrôle en code (D25)
et bridage des suggestions par la règle de corroboration (D18).
"""

from __future__ import annotations

import json
import re
from datetime import date

from .config import ECHIQUIERS, VRAISEMBLANCE

MAX_MOUVEMENTS = 3
MAX_HORS_RADAR = 2
STATUTS_SUGGERES = ("renforcee", "affaiblie", "maintenir")
REF = re.compile(r"\[?\bSIG(\d+)\b\]?")

SYSTEME = """Tu rédiges le brief hebdomadaire d'un analyste de veille stratégique.
Domaine : {domaine}. Finalité : {finalite}

## Méthode imposée : F-T-T (Formuler → Tester → Tracer)
Identifie au plus {max_mouvements} MOUVEMENTS de la semaine : un mouvement est un ensemble de faits
qui fait bouger au moins une hypothèse. Moins de mouvements valent mieux que des mouvements faibles :
si la semaine est pauvre, n'en retiens qu'un ou deux. Pour chacun :
- FORMULER : la lecture que chaque hypothèse concernée donne des faits, une CONTRE-LECTURE obligatoire
  (une autre explication des mêmes faits), et les signaux qu'on devrait observer si chaque lecture est juste.
- TESTER : les éléments de preuve ET de contre-preuve, chacun rattaché aux signaux qui le fondent.
  Utilise ce qu'a relevé l'avocat du diable : dis si le falsificateur a été observé, ou non.
- TRACER : ce qui reste incertain, et ce qu'il faut surveiller la semaine prochaine.

## Règles absolues
1. Chaque élément de preuve cite au moins un signal du dossier sous la forme SIG123. Tu n'utilises
   AUCUN fait absent du dossier, même si tu le connais par ailleurs.
2. Vraisemblance : uniquement « probable », « plausible » ou « peu probable ». Jamais de verdict,
   jamais « certain », « confirmé », « prouvé ».
3. Sépare le fait (ce que dit la source) de l'interprétation (ce que tu en tires).
4. Corroboration : le dossier indique, par hypothèse et par sens, si la corroboration est suffisante
   (≥ 2 sources indépendantes de nature différente). Une reprise ne compte pas. Ne suggère
   « renforcee » ou « affaiblie » que si elle est suffisante ; sinon suggère « maintenir » et dis ce qui manque.
5. Tu proposes, l'analyste tranche : formule les suggestions comme des propositions motivées.
6. Enchaînements : signale une chaîne de cause à effet entre échiquiers (concurrentiel, institutionnel,
   société civile) seulement si les signaux la montrent, en citant au moins deux signaux d'échiquiers différents.
7. Hors radar : choisis au plus {max_hors_radar} signaux parmi "hors_radar_candidats" qui pourraient
   annoncer quelque chose qu'aucune hypothèse ne prévoit, et dis pourquoi en une phrase.
8. Français, phrases courtes. Pas de remplissage.

## Format de sortie : UNIQUEMENT ce JSON
{{
 "synthese": "2 phrases maximum sur la semaine",
 "mouvements": [
  {{"titre": "...", "questions": ["Q2"], "hypotheses": ["H2-A", "H2-B"],
    "formuler": {{"lectures": [{{"hypothese": "H2-A", "lecture": "..."}}],
                  "contre_lecture": "...",
                  "signaux_attendus": ["si H2-A : ...", "si H2-B : ..."]}},
    "tester": {{"elements": [{{"fait": "...", "interpretation": "...", "sens": "soutient", "hypothese": "H2-A", "signaux": ["SIG12", "SIG40"]}}],
               "avocat_du_diable": "falsificateur observé ou non, en une phrase"}},
    "tracer": {{"incertitudes": ["..."], "a_surveiller": ["..."]}},
    "vraisemblance": [{{"hypothese": "H2-A", "niveau": "plausible", "justification": "..."}}],
    "suggestions": [{{"hypothese": "H2-A", "statut_suggere": "maintenir", "motif": "..."}}]
  }}
 ],
 "enchainements": [{{"description": "...", "signaux": ["SIG12", "SIG40"]}}],
 "hors_radar": [{{"signal": "SIG77", "pourquoi": "..."}}]
}}
"""


def construire_systeme(domaine: dict) -> str:
    return SYSTEME.format(
        domaine=domaine["domaine"],
        finalite=" ".join(domaine["finalite"].split()),
        max_mouvements=MAX_MOUVEMENTS,
        max_hors_radar=MAX_HORS_RADAR,
    )


def construire_message(dossier: dict) -> str:
    return "Dossier de la semaine :\n" + json.dumps(dossier, ensure_ascii=False, indent=1)


# ───────────── Contrôle (D25) ─────────────

class Controle:
    def __init__(self, ids_signaux: set[str]):
        self.ids = ids_signaux
        self.elements_retires = 0
        self.references_retirees = 0
        self.suggestions_bridees = 0
        self.vocabulaire_corrige = 0
        self.enchainements_retires = 0

    def refs(self, valeurs) -> list[str]:
        sortie = []
        for v in valeurs or []:
            m = REF.fullmatch(str(v).strip())
            sid = f"SIG{m.group(1)}" if m else None
            if sid in self.ids and sid not in sortie:
                sortie.append(sid)
            elif sid not in sortie:
                self.references_retirees += 1
        return sortie

    def texte(self, valeur, longueur: int = 600) -> str:
        """Nettoie un texte libre : toute mention SIG123 absente du dossier devient « [non sourcé] »."""
        t = " ".join(str(valeur or "").split())[:longueur]

        def remplacer(m):
            sid = f"SIG{m.group(1)}"
            if sid in self.ids:
                return sid
            self.references_retirees += 1
            return "[non sourcé]"

        return REF.sub(remplacer, t)

    def resume(self) -> dict:
        return {
            "elements_retires": self.elements_retires,
            "references_retirees": self.references_retirees,
            "suggestions_bridees": self.suggestions_bridees,
            "vocabulaire_corrige": self.vocabulaire_corrige,
            "enchainements_retires": self.enchainements_retires,
        }


def valider(brut, dossier: dict) -> dict:
    if not isinstance(brut, dict):
        raise ValueError("Le brief n'est pas un objet JSON")
    ids_signaux = {s["id"] for s in dossier["signaux"]}
    echiquier_de = {s["id"]: s.get("echiquier") for s in dossier["signaux"]}
    hyp = {h["id"]: h for h in dossier["hypotheses"]}
    ids_questions = {q["id"] for q in dossier["questions"]}
    c = Controle(ids_signaux)

    mouvements = []
    for m in (brut.get("mouvements") or [])[:MAX_MOUVEMENTS]:
        if not isinstance(m, dict) or not m.get("titre"):
            continue
        f, t, tr = m.get("formuler") or {}, m.get("tester") or {}, m.get("tracer") or {}

        elements = []
        for e in t.get("elements") or []:
            if not isinstance(e, dict):
                continue
            refs = c.refs(e.get("signaux"))
            if not refs or e.get("sens") not in ("soutient", "contredit") or e.get("hypothese") not in hyp:
                c.elements_retires += 1
                continue
            elements.append(
                {
                    "fait": c.texte(e.get("fait")),
                    "interpretation": c.texte(e.get("interpretation")),
                    "sens": e["sens"],
                    "hypothese": e["hypothese"],
                    "signaux": refs,
                }
            )

        vraisemblance = []
        for v in m.get("vraisemblance") or []:
            if isinstance(v, dict) and v.get("hypothese") in hyp:
                niveau = str(v.get("niveau") or "").strip().lower()
                if niveau not in VRAISEMBLANCE:
                    c.vocabulaire_corrige += 1
                    continue
                vraisemblance.append({"hypothese": v["hypothese"], "niveau": niveau, "justification": c.texte(v.get("justification"), 400)})

        suggestions = []
        for s in m.get("suggestions") or []:
            if not isinstance(s, dict) or s.get("hypothese") not in hyp or s.get("statut_suggere") not in STATUTS_SUGGERES:
                continue
            statut, motif = s["statut_suggere"], c.texte(s.get("motif"), 400)
            if statut != "maintenir":
                sens = "soutient" if statut == "renforcee" else "contredit"
                corr = hyp[s["hypothese"]]["corroboration"][sens]
                if not corr["suffisante"]:
                    c.suggestions_bridees += 1
                    motif = (
                        f"{motif} — Suggestion « {statut} » bridée : corroboration insuffisante "
                        f"({corr['domaines_independants']} source(s) indépendante(s), nature(s) : {', '.join(corr['natures']) or 'aucune'})."
                    )
                    statut = "maintenir"
            if any(x["hypothese"] == s["hypothese"] for x in suggestions):
                continue
            suggestions.append({"hypothese": s["hypothese"], "statut_suggere": statut, "motif": motif})

        mouvements.append(
            {
                "titre": c.texte(m["titre"], 150),
                "questions": [q for q in (m.get("questions") or []) if q in ids_questions],
                "hypotheses": [h for h in (m.get("hypotheses") or []) if h in hyp],
                "formuler": {
                    "lectures": [
                        {"hypothese": l["hypothese"], "lecture": c.texte(l.get("lecture"))}
                        for l in f.get("lectures") or []
                        if isinstance(l, dict) and l.get("hypothese") in hyp
                    ],
                    "contre_lecture": c.texte(f.get("contre_lecture")),
                    "signaux_attendus": [c.texte(x, 300) for x in (f.get("signaux_attendus") or [])[:4]],
                },
                "tester": {"elements": elements, "avocat_du_diable": c.texte(t.get("avocat_du_diable"), 400)},
                "tracer": {
                    "incertitudes": [c.texte(x, 300) for x in (tr.get("incertitudes") or [])[:4]],
                    "a_surveiller": [c.texte(x, 300) for x in (tr.get("a_surveiller") or [])[:4]],
                },
                "vraisemblance": vraisemblance,
                "suggestions": suggestions,
            }
        )
    # Un mouvement sans aucun élément sourcé n'est pas un mouvement : on le retire.
    mouvements = [m for m in mouvements if m["tester"]["elements"]]

    enchainements = []
    for e in brut.get("enchainements") or []:
        if not isinstance(e, dict):
            continue
        refs = c.refs(e.get("signaux"))
        echiquiers = {echiquier_de.get(r) for r in refs} & set(ECHIQUIERS)
        if len(refs) < 2 or len(echiquiers) < 2:
            c.enchainements_retires += 1
            continue
        enchainements.append({"description": c.texte(e.get("description")), "signaux": refs, "echiquiers": sorted(echiquiers)})

    hors_radar = []
    candidats = set(dossier.get("hors_radar_candidats") or [])
    for h in brut.get("hors_radar") or []:
        if isinstance(h, dict) and h.get("signal") in candidats and len(hors_radar) < MAX_HORS_RADAR:
            if all(x["signal"] != h["signal"] for x in hors_radar):
                hors_radar.append({"signal": h["signal"], "pourquoi": c.texte(h.get("pourquoi"), 300)})

    return {
        "semaine": dossier["semaine"],
        "synthese": c.texte(brut.get("synthese"), 500),
        "mouvements": mouvements,
        "enchainements": enchainements,
        "hors_radar": hors_radar,
        "echiquiers_14_jours": dossier["echiquiers_14_jours"],
        "echiquiers_silencieux": dossier["echiquiers_silencieux"],
        "suggestions_archivage": dossier["suggestions_archivage"],
        "hypotheses_en_attente": [h["id"] for h in dossier.get("hypotheses_en_attente", [])],
        "nb_signaux_dossier": len(dossier["signaux"]),
        "controle": c.resume(),
    }


# ───────────── Rendu ─────────────

NOMS_ECHIQUIERS = {"concurrentiel": "concurrentiel", "institutionnel": "institutionnel", "societe_civile": "société civile"}
NOMS_STATUTS = {"renforcee": "renforcée", "affaiblie": "affaiblie", "maintenir": "maintenir"}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def date_longue(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def en_markdown(brief: dict, dossier: dict, url_cockpit: str = "") -> str:
    sig = {s["id"]: s for s in dossier["signaux"]}

    def liens(refs):
        return ", ".join(f"[{sig[r]['media']}]({sig[r]['url']})" if sig[r].get("url") else sig[r]["media"] for r in refs if r in sig)

    def citer(texte):
        return REF.sub(lambda m: f"[{sig[f'SIG{m.group(1)}']['media']}]({sig[f'SIG{m.group(1)}']['url']})" if f"SIG{m.group(1)}" in sig else m.group(0), texte)

    L = [f"# Brief de veille — semaine du {date_longue(brief['semaine'])}", ""]
    if brief["synthese"]:
        L += [f"> {citer(brief['synthese'])}", ""]
    if url_cockpit:
        L += [f"**[Ouvrir le cockpit pour trancher]({url_cockpit})**", ""]

    if not brief["mouvements"]:
        L += ["_Aucun mouvement suffisamment sourcé cette semaine._", ""]
    for n, m in enumerate(brief["mouvements"], 1):
        L += [f"## {n}. {citer(m['titre'])}", ""]
        meta = []
        if m["questions"]:
            meta.append("Questions : " + ", ".join(m["questions"]))
        if m["hypotheses"]:
            meta.append("Hypothèses : " + ", ".join(m["hypotheses"]))
        if meta:
            L += ["*" + " · ".join(meta) + "*", ""]

        L += ["### Formuler"]
        for l in m["formuler"]["lectures"]:
            L.append(f"- **{l['hypothese']}** — {citer(l['lecture'])}")
        if m["formuler"]["contre_lecture"]:
            L.append(f"- **Contre-lecture** — {citer(m['formuler']['contre_lecture'])}")
        for s in m["formuler"]["signaux_attendus"]:
            L.append(f"- Signal attendu : {citer(s)}")
        L += ["", "### Tester", "", "| Fait | Interprétation | Sens | Sources |", "|---|---|---|---|"]
        for e in m["tester"]["elements"]:
            sens = "▲ soutient" if e["sens"] == "soutient" else "▼ contredit"
            L.append(f"| {citer(e['fait'])} | {citer(e['interpretation'])} | {sens} {e['hypothese']} | {liens(e['signaux'])} |")
        if m["tester"]["avocat_du_diable"]:
            L += ["", f"**Avocat du diable** — {citer(m['tester']['avocat_du_diable'])}"]
        L += ["", "### Tracer"]
        for i in m["tracer"]["incertitudes"]:
            L.append(f"- Incertitude : {citer(i)}")
        for a in m["tracer"]["a_surveiller"]:
            L.append(f"- À surveiller : {citer(a)}")
        if m["vraisemblance"]:
            L += ["", "**Vraisemblance**"]
            for v in m["vraisemblance"]:
                L.append(f"- {v['hypothese']} : **{v['niveau']}** — {citer(v['justification'])}")
        if m["suggestions"]:
            L += ["", "**Suggestions (à trancher dans le cockpit)**"]
            for s in m["suggestions"]:
                L.append(f"- {s['hypothese']} → *{NOMS_STATUTS[s['statut_suggere']]}* — {citer(s['motif'])}")
        L.append("")

    if brief["enchainements"]:
        L += ["## Enchaînements entre échiquiers", ""]
        for e in brief["enchainements"]:
            L.append(f"- {citer(e['description'])} ({' → '.join(NOMS_ECHIQUIERS[x] for x in e['echiquiers'])} ; {liens(e['signaux'])})")
        L.append("")
    if brief["hors_radar"]:
        L += ["## Hors radar", ""]
        for h in brief["hors_radar"]:
            s = sig[h["signal"]]
            L.append(f"- [{s['titre']}]({s.get('url', '')}) ({s['media']}) — {citer(h['pourquoi'])}")
        L.append("")

    alertes = []
    for e in brief["echiquiers_silencieux"]:
        alertes.append(f"- **Angle mort** : aucun signal pertinent sur l'échiquier *{NOMS_ECHIQUIERS[e]}* depuis 14 jours. Vérifier les sources.")
    for a in brief["suggestions_archivage"]:
        alertes.append(f"- **Archivage suggéré** : {a['hypothese']} — {a['motif']} (dernier signal : {a['depuis']}).")
    if brief["hypotheses_en_attente"]:
        alertes.append(f"- **Hypothèses en attente de validation** : {', '.join(brief['hypotheses_en_attente'])}.")
    if alertes:
        L += ["## Points d'attention", "", *alertes, ""]

    comptes = brief["echiquiers_14_jours"]
    c = brief["controle"]
    L += [
        "---",
        f"*Dossier : {brief['nb_signaux_dossier']} signaux pertinents. Échiquiers sur 14 jours : "
        + ", ".join(f"{NOMS_ECHIQUIERS[k]} {v}" for k, v in comptes.items())
        + f". Contrôle des sources : {c['elements_retires']} élément(s) non sourcé(s) retiré(s), "
        f"{c['references_retirees']} référence(s) invalide(s), {c['suggestions_bridees']} suggestion(s) bridée(s) par la règle de corroboration.*",
    ]
    return "\n".join(L)
