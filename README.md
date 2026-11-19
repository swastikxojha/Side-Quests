# Side Quests

Side Quests turns personal interests into daily, weekly, and monthly challenges. This starter is a FastAPI application with a vanilla HTML/CSS/JavaScript interface and PostgreSQL persistence.

## Run locally

1. Copy `.env.example` to `.env`, replace the local database password, and set a random `SECRET_KEY` of at least 32 characters (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
2. Run `docker compose up --build`.
3. Open http://localhost:8000. API documentation is at `/docs`.

For a lightweight development run without Docker, create a virtual environment, install `requirements-dev.txt`, then run `uvicorn app.main:app --reload`. With no `DATABASE_URL`, the app uses a local SQLite file for development; production runs on PostgreSQL through Compose. Copy `.env.example` to `.env` first if using Compose.

The development configuration prints password-reset OTPs to the application log. Configure SMTP before enabling email delivery in production. Never use the development OTP mode in a public deployment. The included Compose database credentials are for local development only; replace them and use a strong `SECRET_KEY` for deployment.

## Database

Alembic creates and upgrades the database schema. The container runs `alembic upgrade head` before starting the web server. Create revisions with `alembic revision --autogenerate -m "description"` and apply them with `alembic upgrade head`. Development startup can create missing tables for convenience; production startup relies on migrations.

The baseline migration uses explicit reviewed operations instead of generating tables dynamically from the live models. Later changes are separate Alembic revisions. The baseline safely skips table creation when upgrading early development databases that already created their schema automatically.

## Tests

Install development dependencies and run `python -m pytest`. The six tests use isolated SQLite databases and do not require GitHub or a running PostgreSQL instance. The Compose app was also checked locally against PostgreSQL with end-to-end HTTP flows.

## Configuration

See `.env.example`. Configure `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE`, `APP_ENV`, and SMTP settings for deployment. Production startup rejects missing or weak signing keys. Put the app behind HTTPS and configure a production email provider before public launch.

## Included features

Account registration/login, Argon2id password hashes, rate-limited authentication and password reset OTPs, email-or-development-log OTP delivery, interest selection, timezone-aware daily/weekly/monthly quest assignment and due dates, rerolls, multi-step milestones, a prerequisite-gated Python project quest chain and boss quest, progress, completion, XP/levels/ranks, streak display, XP bonus achievements, history, timeframe/category statistics, profile and password settings, account deletion, responsive dashboard, PostgreSQL Compose setup, Alembic migrations, and a basic CI workflow.

## Deployment notes

Use HTTPS, set `APP_ENV=production`, configure a high-entropy `SECRET_KEY`, set `COOKIE_SECURE=true`, replace the development database credentials, configure SMTP, and restrict network access to PostgreSQL. Rate-limit counters are database-backed. The application does not yet include verified account email or external production hosting configuration. Review security settings and monitoring before public launch.

## PostgreSQL backup and restore

With the Compose database running, create a SQL backup with `docker compose exec -T db pg_dump -U sidequests sidequests > sidequests-backup.sql`. Restore it into the configured database with `Get-Content -Raw sidequests-backup.sql | docker compose exec -T db psql -U sidequests sidequests`. Store backups outside the repository and protect them as sensitive user data.
