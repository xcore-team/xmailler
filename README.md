# xmailler

Extension XCore d'envoi d'email asynchrone via SMTP.

## Fonctionnalités

- Envoi direct avec retry automatique (`send`)
- Envoi depuis templates HTML intégrés (`send_template`)
- Envoi en masse avec concurrence contrôlée (`send_bulk`)
- File d'envoi fire-and-forget non bloquant (`queue`)
- Templates intégrés : `welcome`, `password_reset`, `invitation`, `password_changed`, `oauth_linked`, `notification`
- Mode dégradé si SMTP inaccessible (log simulé sans crash)

## Configuration

```yaml
services:
  extensions:
    email:
      module: extensions.xmailler.main:EmailService
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
```

## Utilisation depuis un plugin

```python
email = self.get_service("ext.email")

# Envoi direct
await email.send(to="alice@example.com", subject="Bonjour", body="<h1>Hello</h1>", is_html=True)

# Template intégré
await email.send_template(
    to="alice@example.com",
    template="welcome",
    context={"username": "Alice"}
)

# Envoi en masse (max 5 en parallèle)
await email.send_bulk([
    {"to": "a@example.com", "subject": "Notif", "body": "..."},
    {"to": "b@example.com", "subject": "Notif", "body": "..."},
], max_concurrent=5)

# Fire-and-forget (non bloquant)
email.queue(to="alice@example.com", subject="Notif", body="Message")

# Template custom
email.add_template("mon_template", "<h1>{{ username }}</h1>")
```

## Variables d'environnement

| Variable | Description |
|---|---|
| `XAUTH_SMTP_HOST` | Serveur SMTP |
| `XAUTH_SMTP_PORT` | Port SMTP (ex: 587) |
| `XAUTH_SMTP_USER` | Utilisateur SMTP |
| `XAUTH_SMTP_PASSWORD` | Mot de passe SMTP |
| `XAUTH_SMTP_FROM` | Adresse expéditeur |
| `XAUTH_SMTP_FROM_NAME` | Nom affiché expéditeur |
| `XAUTH_SMTP_USE_TLS` | Activer TLS (`true`/`false`) |

## Structure

```
xmailler/
├── main.py        # EmailService (BaseService)
├── config.py      # EmailConfig, EmailMessage
├── smtp.py        # Transport SMTP (aiosmtplib)
├── templates.py   # Templates HTML intégrés
└── service.yaml   # Manifeste de l'extension
```
