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
          requeue_delay: 30   # secondes, doublé à chaque remise en file (plafond x16)
          max_requeues: 6     # remises en file avant abandon journalisé

Une panne SMTP n'empêche JAMAIS le démarrage : le service reste READY (donc enregistré), signale
l'état dégradé dans /health et les journaux, et réessaie les envois en file.

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

# Délai minimal entre deux sondes SMTP (évite de solliciter le serveur à chaque /health).
_PROBE_MIN_INTERVAL = 15.0


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
        self._smtp_ok = False
        self._degraded_reason = ""
        self._last_probe = 0.0
        self._retry_tasks: set[asyncio.Task] = set()
        self._sent_count = 0
        self._failed_count = 0
        self._queued_count = 0
        self._last_sent_at: float | None = None

    # ── Cycle de vie ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Démarre TOUJOURS le service (READY), même si le SMTP est injoignable.

        Le chargeur d'extensions n'enregistre que les services READY : un état DEGRADED rendrait
        `ext.email` introuvable, donc `auth` et les plugins qui en dépendent ne démarreraient pas.
        Une panne de courrier se voit dans /health (health_check) et les journaux, et les envois
        sont mis en file puis réessayés (voir `_queue_worker`).
        """
        self._status = ServiceStatus.INITIALIZING

        try:
            import aiosmtplib  # noqa: F401
            self._smtp_available = True
        except ImportError:
            self._degraded_reason = "aiosmtplib non installé (pip install aiosmtplib)"
            logger.warning(
                "aiosmtplib non installé — envoi SMTP désactivé. pip install aiosmtplib")

        self._queue = asyncio.Queue(maxsize=self._cfg.queue_size)
        self._worker = asyncio.create_task(
            self._queue_worker(), name="email_queue_worker")
        self._worker.add_done_callback(_swallow_task_exception)

        if self._smtp_available:
            if await self._probe(force=True):
                logger.info(
                    f"EmailService prêt → {self._cfg.smtp_host}:{self._cfg.smtp_port} "
                    f"(from={self._cfg.from_address})"
                )
            else:
                logger.warning(
                    f"EmailService : SMTP injoignable au démarrage — service démarré en mode "
                    f"DÉGRADÉ. {self._degraded_reason}"
                )
        self._status = ServiceStatus.READY

    async def _probe(self, force: bool = False) -> bool:
        """Teste la connexion SMTP (au plus une fois par `_PROBE_MIN_INTERVAL` secondes)."""
        if not self._smtp_available:
            return False
        now = time.monotonic()
        if not force and self._last_probe and now - self._last_probe < _PROBE_MIN_INTERVAL:
            return self._smtp_ok
        self._last_probe = now
        try:
            await asyncio.wait_for(_smtp.test_connection(self._cfg), timeout=self._cfg.timeout + 1)
        except Exception as e:
            self._mark_failed(e)
            return False
        self._mark_ok()
        return True

    def _mark_ok(self) -> None:
        if not self._smtp_ok:
            logger.info("EmailService : SMTP de nouveau joignable — retour à la normale")
        self._smtp_ok = True
        self._degraded_reason = ""

    def _mark_failed(self, exc: Exception) -> None:
        self._smtp_ok = False
        self._degraded_reason = (
            f"SMTP injoignable ({self._cfg.smtp_host}:{self._cfg.smtp_port}) : {exc}. "
            "Vérifier XAUTH_SMTP_HOST, XAUTH_SMTP_PORT, XAUTH_SMTP_USER, XAUTH_SMTP_PASSWORD "
            "et XAUTH_SMTP_USE_TLS ; les e-mails sont mis en file et réessayés."
        )

    async def ensure_ready(self) -> bool:
        """True si l'envoi est possible maintenant (re-sonde le SMTP s'il était dégradé)."""
        return self._smtp_ok or await self._probe()

    async def shutdown(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._worker = None
        for t in list(self._retry_tasks):
            t.cancel()
        self._retry_tasks.clear()
        self._status = ServiceStatus.STOPPED
        logger.info(
            f"EmailService arrêté — {self._sent_count} email(s) envoyé(s)")

    async def health_check(self) -> tuple[bool, str]:
        if not self._smtp_available:
            return False, self._degraded_reason
        if await self._probe():
            return True, f"SMTP {self._cfg.smtp_host}:{self._cfg.smtp_port} accessible"
        return False, self._degraded_reason

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self._status.value,
            "smtp_host": self._cfg.smtp_host,
            "smtp_port": self._cfg.smtp_port,
            "from": self._cfg.from_address,
            "smtp_available": self._smtp_available,
            "degraded": not self._smtp_ok,
            "degraded_reason": self._degraded_reason,
            "queue_size": self._queue.qsize() if self._queue else 0,
            "pending_retries": len(self._retry_tasks),
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

    async def _attempt(self, msg: EmailMessage) -> bool:
        """Envoi avec `max_retries` essais immédiats ; ne compte pas l'échec définitif."""
        for attempt in range(1, self._cfg.max_retries + 1):
            msg.attempts += 1
            try:
                if not self._smtp_available:
                    raise RuntimeError(self._degraded_reason or "SMTP indisponible")
                await _smtp.send_message(self._cfg, msg)
                self._mark_ok()
                self._sent_count += 1
                self._last_sent_at = time.time()
                logger.info(
                    f"Email envoyé → {msg.to} | {msg.subject!r} (tentative {attempt})")
                return True
            except Exception as e:
                if self._smtp_available:
                    self._mark_failed(e)
                logger.warning(
                    f"Email échec (tentative {attempt}/{self._cfg.max_retries}) → {msg.to} : {e}")
                if attempt < self._cfg.max_retries:
                    await asyncio.sleep(2 ** (attempt - 1))
        return False

    async def _send_with_retry(self, msg: EmailMessage) -> bool:
        if await self._attempt(msg):
            return True
        self._failed_count += 1
        logger.error(
            f"Email définitivement échoué → {msg.to} | {msg.subject!r}")
        return False

    def _schedule_requeue(self, msg: EmailMessage) -> None:
        """Remet le message en file après un délai croissant (borné par `max_requeues`)."""
        delay = self._cfg.requeue_delay * min(2 ** msg.requeues, 16)
        msg.requeues += 1

        async def _later() -> None:
            await asyncio.sleep(delay)
            try:
                self._queue.put_nowait(msg)
            except asyncio.QueueFull:
                self._failed_count += 1
                logger.error(f"Email perdu (file pleine) → {msg.to} | {msg.subject!r}")

        task = asyncio.create_task(_later(), name="email_requeue")
        self._retry_tasks.add(task)
        task.add_done_callback(self._retry_tasks.discard)

    async def _queue_worker(self) -> None:
        logger.debug("Email queue worker démarré")
        while True:
            try:
                msg = await self._queue.get()
                try:
                    if await self._attempt(msg):
                        continue
                    if msg.requeues < self._cfg.max_requeues:
                        self._schedule_requeue(msg)
                    else:
                        self._failed_count += 1
                        logger.error(
                            f"Email abandonné après {msg.requeues} remise(s) en file → "
                            f"{msg.to} | {msg.subject!r}. {self._degraded_reason}"
                        )
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue worker erreur inattendue : {e}")
