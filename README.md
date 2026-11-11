# IT Help Desk — Phase 3

A Flask-based, multi-organization IT service platform with a scheduling engine and structured relational data workflows. It supports ticket intake and tracking, technician assignment and status updates, customer service feedback, resource allocation, and comparisons of FCFS, Priority + Aging, and Round Robin.

> **Deployment note:** This is an academic/local prototype, not a production-ready SaaS deployment. The current public ticket form lets a requester select an active organization, and ticket tracking/rating is matched using ticket ID plus requester email (there is no email OTP or customer account login yet). Before serving real client organizations over the internet, add organization-approved customer identity/invitations, HTTPS, managed secrets, rate limiting, audit logging, backups, and a security review.

## Features

### Ticket workflow
- Submit requests with an organization, contact email, category, description, and optional location/asset.
- Generate ticket IDs such as `HD-0023`.
- Track a ticket using its ID and requester email.
- Maintain ticket status history and estimated completion information.
- Technicians can update assigned tickets through a password-protected technician workspace.
- Administrators can assign or reassign tickets and manage technician availability.

### Scheduling engine

All user-facing durations use a 24-hour `HH:MM` duration format (for example, `00:04` for four minutes). The scheduler continues to store and calculate durations internally as integer minutes.
- **FCFS:** non-preemptive First Come, First Served scheduling.
- **Priority + Aging:** non-preemptive priority scheduling; priority 1 is highest and waiting reduces the numeric priority by one level every 00:05 of simulated waiting time, capped at 1.
- **Round Robin:** preemptive time slicing with a configurable quantum (00:01–04:00), optional context-switch overhead (00:00–00:30), multiple execution segments per ticket, context-switch count, and a Gantt chart.
- Scheduling run summaries and per-ticket metrics are persisted. RR execution intervals are stored in `scheduling_segments`.
- A live comparison runs all three algorithms on the same snapshot of READY tickets.
- The schedulers are **simulations**. A simulated completion does not resolve a real ticket or require a technician to change work every quantum.
- The application maps scheduled service intervals to a demonstration workday of 08:00–19:00; overnight gaps are shown in the Gantt chart.

### Technician ratings and service ratings
- After resolution, a requester can submit one service-category rating per ticket and optionally rate the assigned technician.
- Technician ratings and written feedback are visible only in the administrator workspace.
- Service-category ratings are aggregated on the public `/services` page with review counts; individual technician ratings and private feedback are not exposed there.
- Ratings are linked to completed tickets. The current requester check is an email match, not a one-time-password verification.

### Organizations, resources, and analytics
- Create and deactivate client organizations.
- Associate tickets and requesters with organizations; keep organization identifiers on the relevant records.
- Track technician availability, ticket workload, and ratings.
- Maintain resource inventory and active allocations.
- Use Banker's Algorithm to reject allocation requests that would produce an unsafe state, based on the technicians' declared maximum claims.
- Organization-wise ticket counts, service category performance, resource availability, and scheduler metrics are available to administrators.

## Technology

- Python 3.10+
- Flask 3.x
- HTML5, CSS3, vanilla JavaScript
- SQLite for the local demonstration
- MySQL 8+ for the relational database demonstration
- C++17 scheduling executables, with Python fallback implementations

## Quick start — SQLite

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before starting the app:

```env
DB_MODE=sqlite
SECRET_KEY=replace-with-a-long-random-secret
ADMIN_PASSWORD=set-a-strong-admin-password
```

Then run:

```powershell
python app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to set a unique `SECRET_KEY` and strong `ADMIN_PASSWORD`, then run:

```bash
python app.py
```

Open `http://127.0.0.1:5000`. On the first run, tables are created/migrated and a `Campus Demo` organization, categories, and 22 sample tickets are seeded if the database has no tickets. SQLite data is stored in `helpdesk_demo.db` by default.

## MySQL setup

1. Start MySQL Server.
2. Execute `schema.sql` in MySQL 8+ (it creates and selects `helpdesk_db`).
3. Set these values in `.env`:

```env
DB_MODE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=YOUR_MYSQL_PASSWORD
MYSQL_DATABASE=helpdesk_db
SECRET_KEY=replace-with-a-long-random-secret
ADMIN_PASSWORD=set-a-strong-admin-password
```

4. Run `python app.py`. The application checks the schema and runs an additive migration for an existing Phase 2 database. Existing ticket/user data is retained; rows without an organization are assigned to the default `Campus Demo` organization.

Never commit `.env` or real database credentials. For a shared environment, use an application-specific MySQL account with only the permissions it needs instead of `root`.

## C++17 scheduler setup

The app attempts to compile the relevant source file automatically when a scheduler is invoked. It detects `g++` or `clang++`, or uses `CXX` from `.env` when supplied.

- Windows: install MinGW-w64 or another C++17 compiler and add it to `PATH`.
- macOS: install Xcode Command Line Tools or an appropriate compiler.
- Linux: install `g++` or `clang++` from the distribution package manager.

The executables are generated under `build/`. When compilation or execution is unavailable, Python fallback logic is used and the dashboard identifies the engine that ran. To demonstrate the C++ implementation, verify the scheduler engine label in the latest run.

## First-use workflow

1. Open the public home page and submit a ticket under an active organization.
2. Save the generated ticket ID. Track it using the requester email entered during submission.
3. Open **Staff portal → Administrator login** and authenticate as the administrator using `ADMIN_PASSWORD` from `.env`.
4. In the administrator workspace, add technicians with a temporary password, then assign tickets.
5. Sign in through the technician workspace and update an assigned ticket to **In Progress**, **Waiting**, or **Resolved**. A resolution note can be added when resolving.
6. Reopen the ticket tracking page using ticket ID and requester email. A resolved ticket offers service and optional technician rating forms.
7. Open `/services` to view aggregate category ratings. Individual technician ratings remain in the administrator workspace.
8. In the scheduler section, run FCFS, Priority + Aging, or Round Robin. For RR, choose a time quantum and optional context-switch overhead.
9. Use the algorithm comparison table to compare the three policies over the same READY-ticket snapshot.
10. Add resources and allocate them to technicians. The app evaluates the proposed allocation with Banker's Algorithm; release allocations when no longer needed.
11. Register additional organizations to demonstrate organization-linked tickets and administrator reporting.

## Default local administrator account

- Administrator sign-in: `/admin/login`
- Password: the value of `ADMIN_PASSWORD` in `.env`
- The example file contains a placeholder password. Set a strong value before use.

Technicians can open **Staff portal → Technician login**. Technician accounts are created by the administrator in the dashboard. Passwords are stored as password hashes. There is no default technician account.

## Database tables

The schema includes the original tables plus Phase 3 additions:

- `users`, `categories`, `tickets`, `ticket_history`
- `organizations`, `organization_users`
- `technicians`, `ticket_assignments`
- `technician_ratings`, `service_ratings`
- `scheduling_runs`, `scheduling_results`, `scheduling_segments`
- `resources`, `resource_claims`, `resource_allocations`
- Reporting views: `v_technician_performance`, `v_service_category_performance`

`resource_claims` stores each technician's declared maximum claim per resource for the Banker's safety check. `scheduling_segments` stores every RR execution interval because a ticket may run in multiple time slices.

## Tests

Run the scheduler tests from the project directory:

```bash
python -m unittest -v tests_scheduler.py tests_phase3.py tests_database_migration.py
```

The test suite covers the original FCFS/Priority + Aging behavior and the Round Robin scheduler's segments, metrics, arrival handling, context-switch overhead, invalid parameters, and empty input.

## Important behavior and limitations

- Admin access is protected by a single shared password from `ADMIN_PASSWORD`; there is not yet a database-backed multi-admin account system.
- Technicians have separate hashed-password accounts.
- Customer access currently uses ticket ID plus requester-email matching. It is not a customer login or email OTP system and is not sufficient as the sole authentication mechanism for production multi-tenancy.
- Organization selection on the public intake form is suitable for a controlled demonstration, not proof that the requester belongs to that organization. Production deployment should use organization-admin invitations or approved email domains and enforce membership on authenticated customer sessions.
- `/services` intentionally presents aggregate service-category ratings across the service provider's tickets. It does not expose customer identities, ticket descriptions, individual technician ratings, or written private feedback.
- The scheduling comparison is a simulation over the current READY queue and does not mutate ticket status.
- Banker's Algorithm depends on accurate maximum claims entered by the administrator. It is a teaching/demo model, not automatic hardware procurement or device discovery.
- The reset-demo action deletes ticket, history, scheduling, rating, assignment, and allocation records in the connected database and reseeds sample tickets. Use it only with disposable demo data.

## Troubleshooting

- **`ModuleNotFoundError: flask`:** activate the virtual environment and run `pip install -r requirements.txt`.
- **MySQL connection error:** verify that MySQL is running, `helpdesk_db` exists, and credentials/port are correct.
- **Python fallback shown:** install a C++17 compiler and ensure `g++ --version` or `clang++ --version` works in the same terminal that starts Flask.
- **Session/CSRF error:** reload the page and submit the form again. Use a stable `SECRET_KEY` in `.env` so sessions are not invalidated between restarts.
- **Port conflict:** set `PORT=5001` in `.env` and open `http://127.0.0.1:5001`.
