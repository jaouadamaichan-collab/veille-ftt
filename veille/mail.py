"""Envoi du brief par Gmail (mot de passe d'application), avec la même configuration que veille-agent."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

STYLE = """
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1f2933;max-width:760px;margin:auto;line-height:1.5}
 h1{font-size:22px;border-bottom:2px solid #1e3a5f;padding-bottom:6px}
 h2{font-size:18px;color:#1e3a5f;margin-top:28px} h3{font-size:15px;margin-bottom:4px}
 table{border-collapse:collapse;width:100%;font-size:13px} th,td{border:1px solid #d9e2ec;padding:6px;vertical-align:top}
 th{background:#f0f4f8;text-align:left} blockquote{border-left:4px solid #1e3a5f;margin:0;padding:4px 12px;background:#f0f4f8}
 a{color:#1d4ed8}
</style>
"""


def en_html(markdown_texte: str) -> str:
    import markdown

    return "<html><head><meta charset='utf-8'>" + STYLE + "</head><body>" + markdown.markdown(markdown_texte, extensions=["tables"]) + "</body></html>"


def construire(expediteur: str, destinataire: str, sujet: str, markdown_texte: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = sujet, expediteur, destinataire
    msg.attach(MIMEText(markdown_texte, "plain", "utf-8"))
    msg.attach(MIMEText(en_html(markdown_texte), "html", "utf-8"))
    return msg


def envoyer(expediteur: str, mot_de_passe: str, destinataire: str, sujet: str, markdown_texte: str) -> None:
    msg = construire(expediteur, destinataire, sujet, markdown_texte)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(expediteur, mot_de_passe)
        smtp.send_message(msg)
