from __future__ import annotations

import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import EmailConfig, EmailMessage


async def make_smtp(cfg: "EmailConfig"):
    """Ouvre une connexion SMTP authentifiée (STARTTLS si configuré)."""
    import aiosmtplib

    smtp = aiosmtplib.SMTP(
        hostname=cfg.smtp_host,
        port=cfg.smtp_port,
        timeout=cfg.timeout,
    )
    await smtp.connect()
    if cfg.use_tls:
        try:
            await smtp.starttls()
        except aiosmtplib.SMTPException as e:
            if "already" not in str(e).lower():
                raise
    if cfg.smtp_user:
        await smtp.login(cfg.smtp_user, cfg.smtp_password)
    return smtp


async def test_connection(cfg: "EmailConfig") -> None:
    """Vérifie que la connexion SMTP est opérationnelle."""
    smtp = await make_smtp(cfg)
    await smtp.quit()


async def send_message(cfg: "EmailConfig", msg: "EmailMessage") -> None:
    """Construit le MIME et envoie via SMTP."""
    _validate_headers(msg)
    mime = MIMEMultipart("alternative")
    mime["From"] = f"{cfg.from_name} <{cfg.from_address}>"
    mime["To"] = ", ".join([msg.to] if isinstance(msg.to, str) else msg.to)
    mime["Subject"] = msg.subject
    if msg.cc:
        mime["Cc"] = ", ".join(msg.cc)
    if msg.reply_to:
        mime["Reply-To"] = msg.reply_to

    text_body = html_to_text(msg.body) if msg.is_html else msg.body
    mime.attach(MIMEText(text_body, "plain", "utf-8"))
    if msg.is_html:
        mime.attach(MIMEText(msg.body, "html", "utf-8"))

    smtp = await make_smtp(cfg)
    try:
        await smtp.send_message(mime, recipients=msg.recipients)
    finally:
        await smtp.quit()


_HEADER_VALUE_RE = re.compile(r"^[^\r\n]*$")


def _validate_headers(msg: "EmailMessage") -> None:
    """Défense en profondeur anti header-injection : To/Subject/Cc/Reply-To
    finissent en en-têtes MIME bruts (politique compat32, sans validation
    native) — un "\\nBcc: ..." y injecterait des en-têtes arbitraires.
    Lève ValueError (attrapée par _send_with_retry côté service, et refusée
    en amont par le plugin chat) plutôt que d'envoyer un message piégé."""
    recipients = [msg.to] if isinstance(msg.to, str) else list(msg.to)
    for addr in recipients + list(msg.cc or []) + list(msg.bcc or []):
        if not isinstance(addr, str) or _HEADER_VALUE_RE.match(addr) is None or "@" not in addr:
            raise ValueError(f"Adresse email invalide ou dangereuse : {addr!r}")
    for label, value in (("Subject", msg.subject), ("Reply-To", msg.reply_to or "")):
        if _HEADER_VALUE_RE.match(value) is None:
            raise ValueError(f"En-tête {label} invalide (retour à la ligne interdit)")


def html_to_text(html: str) -> str:
    """Conversion HTML → texte simple (sans dépendance externe)."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
