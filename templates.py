from __future__ import annotations

from typing import Any

# ── Styles partagés ────────────────────────────────────────────────────────────

_BASE_STYLE = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;"
    "max-width:600px;margin:auto;padding:32px 20px;color:#1f2937;"
)
_FOOTER = (
    "<hr style='border:none;border-top:1px solid #e5e7eb;margin:32px 0;'>"
    "<p style='color:#9ca3af;font-size:12px;text-align:center;'>{app_name}</p>"
)

# ── Catalogue de templates ─────────────────────────────────────────────────────
# Pour modifier un template : éditer ici uniquement.
# Pour en ajouter un : créer une nouvelle entrée + un sender dans le plugin.

TEMPLATES: dict[str, str] = {
    "welcome": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Bienvenue</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h1 style='color:#2563eb;font-size:24px;'>Bienvenue, {username} !</h1>"
        "<p>Votre compte sur <strong>{app_name}</strong> a été créé avec succès.</p>"
        "<p>Vous pouvez dès maintenant vous connecter et explorer toutes les fonctionnalités.</p>"
        f"{_FOOTER}</body></html>"
    ),
    "password_reset": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Réinitialisation</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h2 style='color:#dc2626;'>Réinitialisation de mot de passe</h2>"
        "<p>Bonjour {username},</p>"
        "<p>Une demande de réinitialisation a été effectuée pour votre compte.</p>"
        "<p style='margin:28px 0;'>"
        "<a href='{reset_url}' style='background:#dc2626;color:#fff;padding:13px 28px;"
        "text-decoration:none;border-radius:6px;font-weight:600;'>Réinitialiser mon mot de passe</a>"
        "</p>"
        "<p style='color:#6b7280;font-size:13px;'>Ce lien expire dans {expires_in_minutes} minutes.<br>"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.</p>"
        f"{_FOOTER}</body></html>"
    ),
    "invitation": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Invitation</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h2 style='color:#2563eb;'>Vous êtes invité à rejoindre <strong>{tenant_name}</strong></h2>"
        "<p><strong>{invited_by}</strong> vous invite à rejoindre cet espace de travail.</p>"
        "<p style='margin:28px 0;'>"
        "<a href='{accept_url}' style='background:#2563eb;color:#fff;padding:13px 28px;"
        "text-decoration:none;border-radius:6px;font-weight:600;'>Accepter l'invitation</a>"
        "</p>"
        "<p style='color:#6b7280;font-size:13px;'>Ce lien expire dans {expires_hours}h.</p>"
        f"{_FOOTER}</body></html>"
    ),
    "password_changed": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Mot de passe modifié</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h2 style='color:#059669;'>Mot de passe modifié</h2>"
        "<p>Bonjour {username},</p>"
        "<p>Le mot de passe de votre compte a été modifié avec succès.</p>"
        "<p style='color:#6b7280;font-size:13px;'>"
        "Si vous n'êtes pas à l'origine de cette modification, contactez le support immédiatement.</p>"
        f"{_FOOTER}</body></html>"
    ),
    "oauth_linked": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Compte lié</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h2 style='color:#2563eb;'>Compte {provider} lié</h2>"
        "<p>Bonjour {username},</p>"
        "<p>Votre compte <strong>{provider}</strong> ({provider_email}) a été lié à votre profil.</p>"
        "<p style='color:#6b7280;font-size:13px;'>"
        "Si vous n'êtes pas à l'origine de cette action, contactez le support.</p>"
        f"{_FOOTER}</body></html>"
    ),
    "notification": (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{{subject}}</title></head>"
        f"<body style='{_BASE_STYLE}'>"
        "<h2 style='color:#1f2937;'>{title}</h2>"
        "<p>{message}</p>"
        "{action_button}"
        f"{_FOOTER}</body></html>"
    ),
}


def render(name: str, context: dict[str, Any]) -> str:
    """Rendu d'un template par substitution de {clé}."""
    tpl = TEMPLATES.get(name)
    if not tpl:
        raise KeyError(
            f"Template email inconnu : '{name}'. Disponibles : {list(TEMPLATES.keys())}")
    try:
        return tpl.format(**context)
    except KeyError as e:
        raise ValueError(f"Template '{name}' : variable manquante {e}") from e
