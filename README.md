# Side Quests

Side Quests turns personal interests into daily, weekly, and monthly challenges. This starter is a FastAPI application with a vanilla HTML/CSS/JavaScript interface and PostgreSQL persistence.

## Run locally

1. Copy `.env.example` to `.env` and set a long random `SECRET_KEY`.
2. Run `docker compose up --build`.
3. Open http://localhost:8000. API documentation is at `/docs`.

The development configuration prints password-reset OTPs to the application log. Configure SMTP before enabling email delivery in production. Never use the development OTP mode in a public deployment. The included Compose database credentials are for local development only; replace them and use a strong `SECRET_KEY` for deployment.

## Database

Alembic creates and upgrades the database schema. The container runs `alembic upgrade head` before starting the web server. Create revisions with `alembic revision --autogenerate -m "description"` and apply them with `alembic upgrade head`. Development startup can create missing tables for convenience; production startup relies on migrations.

## Tests

Install dependencies and run `pytest`. Tests use SQLite in-memory and do not require a running PostgreSQL instance.

## Configuration

See `.env.example`. Configure `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE`, `APP_ENV`, and SMTP settings for deployment. Put the app behind HTTPS and configure trusted origins and a production email provider before public launch.

## Included features

Account registration/login, Argon2id password hashes, rate-limited authentication and password reset OTPs, email-or-development-log OTP delivery, interest selection, timezone-aware daily/weekly/monthly quest assignment and due dates, rerolls, progress, completion, XP/levels/ranks, streak display, history, starter achievements, profile and password settings, account deletion, responsive dashboard, PostgreSQL Compose setup, Alembic migrations, and a basic CI workflow.

## Deployment notes

Use HTTPS, set `APP_ENV=production`, configure a high-entropy `SECRET_KEY`, set `COOKIE_SECURE=true`, replace the development database credentials, configure SMTP, and restrict network access to PostgreSQL. Rate-limit counters are database-backed. The application does not yet include verified account email or external production hosting configuration. Review security settings and monitoring before public launch.
