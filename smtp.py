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
