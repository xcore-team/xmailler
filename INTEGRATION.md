# Intégration — xmailler

## 1. Déclarer l'extension dans `integration.yaml`

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

## 2. Récupérer le service depuis un plugin

```python
class MyPlugin(XCorePlugin):
    async def on_load(self):
        self.email = self.get_service("ext.email")
```

## 3. API complète

### `send(to, subject, body, *, is_html, cc, bcc, reply_to) → bool`

```python
ok = await self.email.send(
    to="user@example.com",
    subject="Bienvenue",
    body="<h1>Bonjour !</h1>",
    is_html=True,
)
```

### `send_template(to, template, context, *, subject, cc) → bool`

Templates disponibles : `welcome`, `password_reset`, `invitation`,
`password_changed`, `oauth_linked`, `notification`.

```python
await self.email.send_template(
    to="user@example.com",
    template="welcome",
    context={"username": "Alice"},
)
```

### `send_bulk(messages, max_concurrent) → dict`

```python
result = await self.email.send_bulk([
    {"to": "a@ex.com", "subject": "Notif", "body": "..."},
    {"to": "b@ex.com", "subject": "Notif", "body": "..."},
], max_concurrent=5)
# → {"sent": 2, "failed": 0, "total": 2}
```

### `queue(to, subject, body, *, is_html) → bool`

Non bloquant. Retourne `False` si la file est pleine (`queue_size`).

```python
self.email.queue(to="user@example.com", subject="Notif", body="Texte")
```

### `add_template(name, html_content)`

```python
self.email.add_template("activation", "<h1>Activez votre compte {{ username }}</h1>")
```

## 4. Health check

```python
ok, msg = await self.email.health_check()
# → (True, "SMTP smtp.gmail.com:587 accessible")
```

## 5. Variables d'environnement requises

```dotenv
XAUTH_SMTP_HOST=smtp.gmail.com
XAUTH_SMTP_PORT=587
XAUTH_SMTP_USER=noreply@example.com
XAUTH_SMTP_PASSWORD=secret
XAUTH_SMTP_FROM=noreply@example.com
XAUTH_SMTP_FROM_NAME=XCore Marketplace
XAUTH_SMTP_USE_TLS=true
```

## 6. Mode dégradé

Si SMTP est inaccessible au démarrage, le service passe en `DEGRADED` (pas de crash).
Les appels `send()` loggent le contenu au lieu de l'envoyer, ce qui permet au pipeline de continuer en dev sans serveur mail.
