from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailConfig:
    smtp_host: str = ""  # vide : SMTP non configuré, l'envoi est SIMULÉ (journalisé, jamais envoyé)
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_address: str = "noreply@example.com"
    from_name: str = "xcore App"
    use_tls: bool = True
    timeout: int = 10
    max_retries: int = 3
    queue_size: int = 100

    @property
    def configured(self) -> bool:
        """Un serveur SMTP est-il désigné ? Sinon l'extension simule l'envoi (développement) au lieu d'échouer trois fois."""
        return bool(self.smtp_host)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EmailConfig":
        # Une valeur absente ou vide du YAML retombe sur la variable d'environnement `XAUTH_SMTP_<CLÉ>` (`.env`) : le YAML de l'hôte n'exige pas de
        # `${VAR}` (xcore refuse de démarrer si une variable listée n'existe pas) et le mot de passe SMTP reste hors du dépôt.
        names = {"smtp_host": "HOST", "smtp_port": "PORT", "smtp_user": "USER", "smtp_password": "PASSWORD", "from_address": "FROM", "from_name": "FROM_NAME", "use_tls": "USE_TLS"}

        def _get(key: str, default: Any) -> Any:
            value = d.get(key)
            if value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, str) and re.fullmatch(r"\$\{[^}]*\}", value.strip())):
                value = os.environ.get(f"XAUTH_SMTP_{names[key]}") if key in names else None
            return default if value is None or str(value).strip() == "" else value

        def _str(key: str, default: str) -> str:
            return str(_get(key, default)).strip()

        def _int(key: str, default: int) -> int:
            return int(str(_get(key, default)).strip())

        def _bool(key: str, default: bool) -> bool:
            v = str(_get(key, default)).strip().lower()
            return v not in ("false", "0", "no", "")

        return cls(
            smtp_host=_str("smtp_host", ""),
            smtp_port=_int("smtp_port", 587),
            smtp_user=_str("smtp_user", ""),
            smtp_password=_str("smtp_password", ""),
            from_address=_str("from_address", "noreply@example.com"),
            from_name=_str("from_name", "xcore App"),
            use_tls=_bool("use_tls", True),
            timeout=_int("timeout", 10),
            max_retries=_int("max_retries", 3),
            queue_size=_int("queue_size", 100),
        )


@dataclass
class EmailMessage:
    to: str | list[str]
    subject: str
    body: str
    is_html: bool = False
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str | None = None
    attachments: list[dict] = field(default_factory=list)
    id: str = field(default_factory=lambda: str(time.time_ns()))
    attempts: int = 0
    created_at: float = field(default_factory=time.time)

    @property
    def recipients(self) -> list[str]:
        to = [self.to] if isinstance(self.to, str) else self.to
        return list(set(to + self.cc + self.bcc))
