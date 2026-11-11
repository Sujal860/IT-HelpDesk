# Phase 3 implementation notes

## Included in this package

- C++17 Round Robin scheduler with configurable quantum, context-switch overhead, arrivals, preemption, repeated execution segments, and a Python fallback.
- Persisted Round Robin execution segments and Gantt rendering for preempted jobs.
- FCFS / Priority + Aging / Round Robin comparison using a shared READY-ticket snapshot.
- Additive, repeatable Phase 3 database migration that preserves existing ticket and user rows; creates organization, technician, assignment, rating, resource, allocation, and scheduler-segment structures plus reporting views.
- Admin and technician sign-in flows, technician management, assignment/reassignment, technician status updates, separate technician and service ratings, and organization/resource management.
- Admin-only technician rating details; public service page exposes category aggregates and review counts only.
- Resource allocation safe-state checks using Banker's Algorithm and transaction/locking protections for allocation and release.
- Organization association and tenant filtering in the application workflows.
- Refined the interface with consistent typography, calmer contrast, more deliberate spacing, polished tables/cards, responsive staff navigation, and keyboard focus states.
- Removed visible academic module labels from the product interface and replaced them with service-oriented language.
- Standardized displayed durations as `HH:MM` while preserving integer-minute calculations and storage; Round Robin controls now accept `HH:MM`.
- Updated responsive templates, documentation, `.env.example`, and presentation guide.

## Verification performed in the build environment

- `python -m py_compile app.py database.py phase3_schema.py scheduler_bridge.py tests_scheduler.py tests_phase3.py tests_database_migration.py` — passed.
- `python -m unittest -v tests_scheduler.py tests_phase3.py tests_database_migration.py` — 15 tests passed.
- Jinja parsing — all 8 templates compiled with the custom duration filter.
- Duration-formatting checks — `00:04`, `01:05`, and `02:30` display cases passed; `HH:MM` input parsing and invalid-minute rejection passed.
- C++17 Round Robin scheduler — compiled and exercised successfully.
- SQLite migration checks — existing Phase 2 records preserved, default organization association created, reporting views created, and repeated migration succeeded.
- Route-reference/static SQL checks — performed during implementation; template endpoint references resolved and dashboard query shapes executed against SQLite test data.

## Not verified in this environment

- The Flask application could not be launched for HTTP/browser testing because Flask, Werkzeug, and PyMySQL were not installed in the execution environment and package-network access was unavailable.
- A live MySQL server was not available, so the MySQL migration and row-locking behavior still need a local integration test.
- Browser-specific visual behavior has not been verified in an actual browser. The templates parse and responsive styles are included, but this is not a substitute for a browser QA pass.

## Security / deployment boundary

This is an academic/local prototype, not a production-ready multi-tenant SaaS deployment. Admin access currently uses a shared configured password. Customer ticket tracking and rating are matched using ticket ID plus requester email; there is no customer account login or email OTP. The public intake organization selector is suitable for a controlled demonstration, not proof of organization membership. Before exposing it to real external clients, implement authenticated organization membership/invitations, per-user identity, HTTPS, managed secrets, rate limiting, audit logging, backups, monitoring, and an independent security review.

## Local next steps

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env`, set a strong `SECRET_KEY` and `ADMIN_PASSWORD`, and configure MySQL credentials if using MySQL.
3. Run the unit tests listed in `README.md`.
4. Start the app locally and test admin, technician, requester, rating, assignment, scheduling, and resource workflows in a browser.
5. Before using MySQL for real data, back up the database and run the migration against a staging copy first.
