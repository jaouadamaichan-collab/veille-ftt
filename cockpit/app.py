"""Point d'entrée Streamlit du cockpit. Sur Streamlit Cloud : Main file path = cockpit/app.py

Secrets attendus (Settings → Secrets), au format TOML :
    SUPABASE_URL = "https://xxxx.supabase.co"
    SUPABASE_SERVICE_KEY = "sb_secret_..."
    MOT_DE_PASSE = "..."
"""

import hmac
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veille.cockpit import afficher  # noqa: E402
from veille.db import Base  # noqa: E402

SECRETS = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "MOT_DE_PASSE")

st.set_page_config(page_title="Veille F-T-T", page_icon="🧭", layout="wide")


def lire_secret(nom: str) -> str:
    try:
        return str(st.secrets[nom])
    except Exception:
        return ""


manquants = [n for n in SECRETS if not lire_secret(n)]
if manquants:
    st.error("Secrets manquants : " + ", ".join(manquants))
    try:
        trouves = sorted(st.secrets.keys())
    except Exception:
        trouves = []
    st.caption(f"Secrets lus par l'application : {trouves or 'aucun'}. Vérifiez le format TOML : une ligne par secret, valeur entre guillemets droits.")
    st.stop()

if not st.session_state.get("authentifie"):
    st.title("Veille F-T-T")
    mdp = st.text_input("Mot de passe", type="password")
    if mdp:
        if hmac.compare_digest(mdp, lire_secret("MOT_DE_PASSE")):
            st.session_state["authentifie"] = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    st.stop()


@st.cache_resource
def base() -> Base:
    return Base(lire_secret("SUPABASE_URL"), lire_secret("SUPABASE_SERVICE_KEY"))


afficher(base())
