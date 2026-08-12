"""
Extension email Xcore — transport SMTP asynchrone avec file d'envoi.

Configuration dans int.yaml :
    extensions:
      email:
        module: extensions.mail.main:EmailService
        config:
          smtp_host: ${XAUTH_SMTP_HOST}
          smtp_port: ${XAUTH_SMTP_PORT}
          smtp_user: ${XAUTH_SMTP_USER}
          smtp_password: ${XAUTH_SMTP_PASSWORD}
          from_address: ${XAUTH_SMTP_FROM}
          from_name: ${XAUTH_SMTP_FROM_NAME}
          use_tls: ${XAUTH_SMTP_USE_TLS}
          timeout: 10
          max_retries: 3
          queue_size: 100

Accès depuis un plugin :
    email = self.get_service("ext.email")
    await email.send(to="alice@example.com", subject="Bonjour", body="<h1>Hello</h1>", is_html=True)
    await email.send_template(to="alice@example.com", template="welcome", context={"username": "Alice"})
    email.queue(to="alice@example.com", subject="Notif", body="...")
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from xcore.services.base import BaseService, ServiceStatus

from . import smtp as _smtp
from .config import EmailConfig, EmailMessage
from .templates import TEMPLATES, render

logger = logging.getLogger("xcore.services.email")


def _swallow_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error(f"Email queue worker exception : {exc}")


class EmailService(BaseService):
    """
    Service d'envoi d'email SMTP asynchrone.

      send()           → envoi direct (avec retry)
      send_template()  → envoi depuis un template HTML
      send_bulk()      → envoi en masse (parallèle, max_concurrent)
      queue()          → fire-and-forget non bloquant
      add_template()   → ajoute/remplace un template custom

    Templates intégrés : welcome, password_reset, invitation,
                         password_changed, oauth_linked, notification
    """

    name = "email"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__()
        self._cfg = EmailConfig.from_dict(config)
        self._queue: asyncio.Queue[EmailMessage] | None = None
        self._worker: asyncio.Task | None = None
        self._smtp_available = False
        self._sent_count = 0
        self._failed_count = 0
        self._queued_count = 0
        self._last_sent_at: float | None = None

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        self._status = ServiceStatus.INITIALIZING

        try:
            import aiosmtplib  # noqa: F401
            self._smtp_available = True
        except ImportError:
            logger.warning(
                "aiosmtplib non installé — envoi SMTP désactivé. pip install aiosmtplib")

        self._queue = asyncio.Queue(maxsize=self._cfg.queue_size)
        self._worker = asyncio.create_task(
            self._queue_worker(), name="email_queue_worker")
        self._worker.add_done_callback(_swallow_task_exception)

        if self._smtp_available:
            try:
                await _smtp.test_connection(self._cfg)
                logger.info(
                    f"EmailService prêt → {self._cfg.smtp_host}:{self._cfg.smtp_port} "
                    f"(from={self._cfg.from_address})"
                )
                self._status = ServiceStatus.READY
            except Exception as e:
                logger.warning(
                    f"EmailService : connexion SMTP échouée ({e}) → mode dégradé")
                self._status = ServiceStatus.DEGRADED
        else:
            self._status = ServiceStatus.DEGRADED

    async def shutdown(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._worker = None
        self._status = ServiceStatus.STOPPED
        logger.info(
            f"EmailService arrêté — {self._sent_count} email(s) envoyé(s)")

    async def health_check(self) -> tuple[bool, str]:
        if not self._smtp_available:
            return False, "aiosmtplib non installé"
        try:
            await _smtp.test_connection(self._cfg)
            return True, f"SMTP {self._cfg.smtp_host}:{self._cfg.smtp_port} accessible"
        except Exception as e:
            return False, f"SMTP inaccessible : {e}"

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self._status.value,
            "smtp_host": self._cfg.smtp_host,
            "smtp_port": self._cfg.smtp_port,
            "from": self._cfg.from_address,
            "smtp_available": self._smtp_available,
            "queue_size": self._queue.qsize() if self._queue else 0,
            "sent": self._sent_count,
            "failed": self._failed_count,
            "queued": self._queued_count,
            "last_sent_at": self._last_sent_at,
        }

    # ── API publique ──────────────────────────────────────────────────────────

    async def send(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        *,
        is_html: bool = False,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> bool:
        msg = EmailMessage(
            to=to, subject=subject, body=body,
            is_html=is_html, cc=cc or [], bcc=bcc or [], reply_to=reply_to,
        )
        return await self._send_with_retry(msg)

    async def send_template(
        self,
        to: str | list[str],
        template: str,
        context: dict[str, Any],
        *,
        subject: str | None = None,
        cc: list[str] | None = None,
    ) -> bool:
        context.setdefault("app_name", self._cfg.from_name)
        html_body = render(template, context)
        email_subject = subject or context.get(
            "subject", f"[{self._cfg.from_name}] Notification")
        return await self.send(to=to, subject=email_subject, body=html_body, is_html=True, cc=cc)

    async def send_bulk(
        self,
        messages: list[dict[str, Any]],
        max_concurrent: int = 5,
    ) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _one(msg_dict: dict) -> bool:
            async with semaphore:
                return await self.send(**msg_dict)

        results = await asyncio.gather(*[_one(m) for m in messages])
        sent = sum(1 for r in results if r)
        return {"sent": sent, "failed": len(results) - sent, "total": len(results)}

    def queue(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        *,
        is_html: bool = False,
    ) -> bool:
        """Fire-and-forget — non bloquant. Retourne False si la file est pleine."""
        msg = EmailMessage(to=to, subject=subject, body=body, is_html=is_html)
        try:
            self._queue.put_nowait(msg)
            self._queued_count += 1
            return True
        except asyncio.QueueFull:
            logger.warning(
                f"File email pleine ({self._cfg.queue_size} messages)")
            return False

    def add_template(self, name: str, html_content: str) -> None:
        """Ajoute ou remplace un template HTML."""
        TEMPLATES[name] = html_content
        logger.info(f"EmailService : template '{name}' enregistré")

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _send_with_retry(self, msg: EmailMessage) -> bool:
        for attempt in range(1, self._cfg.max_retries + 1):
            msg.attempts = attempt
            try:
                if not self._smtp_available:
                    logger.info(
                        f"[EMAIL SIMULÉ] To: {msg.to} | Subject: {msg.subject} | "
                        f"Body: {msg.body[:80]}..."
                    )
                    return True
                await _smtp.send_message(self._cfg, msg)
                self._sent_count += 1
                self._last_sent_at = time.time()
                logger.info(
                    f"Email envoyé → {msg.to} | {msg.subject!r} (tentative {attempt})")
                return True
            except Exception as e:
                logger.warning(
                    f"Email échec (tentative {attempt}/{self._cfg.max_retries}) → {msg.to} : {e}")
                if attempt < self._cfg.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))

        self._failed_count += 1
        logger.error(
            f"Email définitivement échoué → {msg.to} | {msg.subject!r}")
        return False

    async def _queue_worker(self) -> None:
        logger.debug("Email queue worker démarré")
        while True:
            try:
                msg = await self._queue.get()
                await self._send_with_retry(msg)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker erreur inattendue : {e}")
