# Side Quests implementation checklist

This checklist follows the original project brief. Items marked **Done** have local test or implementation evidence. Remaining external or deferred items are listed at the end.

## 1. Project foundation

- [x] FastAPI, PostgreSQL, SQLAlchemy, Pydantic, Alembic, and vanilla browser UI
- [x] Local development requirements separated from runtime dependencies
- [x] Compose services for app and PostgreSQL with database health check
- [x] Add Docker build exclusions, non-root runtime, app health check, and restart policy; rebuild and inspect containers
- [x] Replace the metadata-driven initial migration with a reviewed, reproducible schema revision
- [x] Add backup/restore and operational configuration instructions

## 2. Accounts and security

- [x] Registration/login/logout, Argon2id password hashes, signed expiring HttpOnly cookie
- [x] Password reset OTPs with expiry, attempt limits, rate limits, keyed digests, generic response, optional SMTP delivery
- [x] Database-backed rate limiting for sensitive account routes
- [x] Profile editing, password change, account deletion, timezone setting
- [x] Improve reset flow to use a proper accessible screen instead of browser prompts
- [x] Reject weak or placeholder production signing keys; use Secure cookies behind HTTPS and baseline security headers
- [ ] Add account email verification; SMTP delivery is available for password resets, but no SMTP credentials are configured here

## 3. Interests and quests

- [x] One to three interests and a separate quest-template catalogue
- [x] Idempotent 3 daily / 2 weekly / 1 monthly assignment with timezone-aware due dates
- [x] Interest-specific template choices, difficulty, estimate, and category
- [x] Reroll history and cumulative half-XP rule, with a three-reroll cap and reward floor
- [x] Completion ownership checks, duplicate-award prevention, XP ledger, quest history
- [x] Add relational quest milestones and updateable multi-step progress
- [x] Add quest chains and prerequisite/boss quest progression
- [x] Persist expired quests in history and display status and due dates in quest/history views

## 4. Progress and gamification

- [x] Nonlinear level thresholds, rank labels, XP progress, streak calculation
- [x] Starter achievements for first quest, 10/100 quests, seven-day streak, monthly completion, and category milestones
- [x] Award and ledger achievement bonus XP with duplicate protection
- [x] Add a visible statistics view with timeframe/category summaries
- [x] Add tests for 10/100 quest achievement thresholds, seven-day streak boundaries, and duplicate award protection

## 5. Interface and accessibility

- [x] Responsive dark adventure-themed dashboard, onboarding, quest cards, history, achievements, settings
- [x] Semantic forms, keyboard focus, reduced-motion handling, and status messaging
- [x] Replace browser alerts/prompts with in-app dialogs and toasts
- [x] Add empty states and in-app error feedback for data views
- [x] Add loading indicator and explicit retry controls
- [x] Inspect desktop UI and mobile layout; fix narrow-screen overflow

## 6. Verification and release

- [x] Local Python tests, lint checks, migration smoke test, and local HTTP smoke test
- [x] Run the complete Python test suite locally (6 passed); tests use isolated SQLite
- [x] Rebuild Compose image and verify app and PostgreSQL health checks; startup migrations apply cleanly
- [x] Run PostgreSQL-backed local HTTP checks for auth, reset, ownership, quest lifecycle, profile, history, stats, and delete
- [x] Update README run/test instructions, backups, deployment settings, and known external setup
- [ ] Push verified changes to `main`; confirm local tree is clean apart from workspace instructions

## Remaining before a public production launch

- Configure a real SMTP provider and implement/enable account email verification.
- Set strong production secrets, secure database credentials, HTTPS/domain, backups, monitoring, and hosting-specific health/rollback settings.
