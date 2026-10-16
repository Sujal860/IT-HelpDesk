# HelpDesk — OS + DBMS (Phase 2 / 40% Prototype)

A working college-project prototype for submitting and tracking help-desk tickets, storing them in a relational database, and demonstrating OS scheduling concepts through a separate C++17 FCFS program.

## What works in this phase

- Ticket submission form with server-side validation.
- Ticket IDs such as `HD-0001` and a ticket tracking page.
- Persistent records for users, categories, tickets, and ticket status history.
- Seeded campus IT scenario (22 realistic tickets with different categories, priorities, service-duration estimates, and statuses).
- Admin dashboard showing ticket totals, READY queue, open/resolved counts, and ticket records.
- FCFS (First Come, First Served) scheduling implemented in C++17, invoked by Flask as a separate executable.
- FCFS results saved to `scheduling_runs` and `scheduling_results`.
- Gantt chart plus average waiting, response, turnaround, throughput, and utilization metrics.
- Preliminary approximate completion estimate is calculated when a ticket is submitted; admin can rerun FCFS to refresh the queue estimates. A simulation never resolves a ticket.
- Python FCFS fallback only when no C++ compiler is installed. The dashboard labels the engine clearly; for a C++ demonstration, install a compiler and ensure the engine label says `C++17 executable`.

## Technology

- Frontend: HTML5, CSS3, vanilla JavaScript
- Backend: Python 3 + Flask
- Database: MySQL (recommended for the DBMS demonstration) or SQLite (quick local demo mode)
- OS scheduler: C++17

## 1. Run the quick local demo

Python 3.10+ is recommended.

### Windows (PowerShell)

```powershell
cd helpdesk_40_percent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`. The default `DB_MODE=sqlite` makes the app usable immediately without MySQL credentials. SQLite data persists in `helpdesk_demo.db`; it is not a replacement for the intended MySQL DBMS demo.

### macOS / Linux

```bash
cd helpdesk_40_percent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## 2. Use MySQL for your DBMS demonstration

1. Start MySQL Server from your local MySQL installation.
2. Open MySQL Workbench and execute `schema.sql`. The script creates/uses `helpdesk_db` and defines the tables.
3. Copy `.env.example` to `.env` (or set environment variables in your terminal), then set:

```env
DB_MODE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=YOUR_MYSQL_PASSWORD
MYSQL_DATABASE=helpdesk_db
```

4. Restart the Flask app. `app.py` will verify/create the required tables and load demo tickets if the ticket table is empty.

The app reads `.env` automatically only if you add the following near the top of `app.py` after installing `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()
```

Place those two lines before importing `database`. Alternatively, export the variables in your shell before running `python app.py`. For a student demo, either method is fine. **Never submit or commit your real MySQL password.**

## 3. Make sure the C++17 scheduler is used

The app tries to compile `cpp/fcfs_scheduler.cpp` automatically using `g++` or `clang++` when the administrator runs FCFS.

- Windows: install a working MinGW-w64 distribution (g++), add its `bin` folder to PATH, and restart VS Code/PowerShell.
- Verify with `g++ --version` and `g++ -std=c++17 --version`.
- macOS: install command-line tools or `g++`/`clang++`.
- Linux: install the `g++` package using your distribution's package manager.

The compiled binary is placed in `build/`. If compilation is unavailable, the same FCFS logic runs in a clearly-labelled Python fallback so the rest of the demo still works.

## 4. Demo flow for the presentation

1. Open **Home** and show that realistic sample tickets are already stored.
2. Submit a fresh ticket using a name, email, issue title, category, location, and description.
3. Note the generated ticket ID (for example `HD-0023`) and open its tracking page. A preliminary FCFS run is triggered after submission to provide an initial estimate.
4. Open **Admin dashboard** and show Total Tickets, READY Queue, Open Work, and status counts.
5. Click **Run FCFS simulation** to refresh the estimates and create a visible, saved scheduling run for the presentation.
6. Explain the Gantt chart and metrics: arrival, service, start, completion, waiting, turnaround, response, throughput, and utilization.
7. Return to Track Ticket. Its approximate ETA is available, while the ticket remains `READY` until an actual technician status workflow is added.
8. Refresh/restart the Flask app and show persistence.

## FCFS definitions

For each ticket/job:

- `Start = max(previous completion, arrival)`
- `Completion = Start + Service Time`
- `Waiting = Start - Arrival`
- `Turnaround = Completion - Arrival`
- `Response = First Start - Arrival` (same as waiting in this non-preemptive FCFS model)
- `Throughput = completed jobs / elapsed simulation minutes`
- `Utilization = total service time / elapsed simulation time × 100%`

Arrival and service values are **simulation minutes**, independent of real timestamps. For this first phase, one simulated service lane is used. Multi-technician dispatch is planned for the next phase.

## Database tables in the 40% phase

- `users`
- `categories`
- `tickets`
- `ticket_history`
- `scheduling_runs`
- `scheduling_results`

See `schema.sql` for the MySQL schema. Use one shared database named `helpdesk_db` for the team.

## Current limitations / later milestones

- No production-grade authentication or role permissions yet; `/admin` is a demonstration dashboard. Keep this prototype local and do not expose it publicly.
- FCFS is implemented now. Priority Scheduling with Aging and Round Robin are later milestones.
- Technician management, assignment transactions, resource allocation, comments, and feedback are later milestones.
- ETA is an approximate simulation projection and uses a single service lane in this phase.
- The admin reset button deletes records in the local demo database and reseeds the sample scenario. Do not use it on real data.

## Troubleshooting

- **Cannot connect to MySQL:** check that MySQL Server is running, the database exists, credentials are correct, and the port is `3306`.
- **It says Python fallback:** install/configure `g++`, add it to PATH, restart the terminal, then run FCFS again.
- **ModuleNotFoundError: flask/pymysql:** activate `.venv` and run `pip install -r requirements.txt`.
- **Port 5000 already in use:** set `PORT=5001` in the environment and open `http://127.0.0.1:5001`.

## Project status

This is the requested first 40% prototype for the second-phase demonstration, not the final 100% application. It prioritizes a fully connected path: browser form → database → FCFS engine → persisted metrics/Gantt chart → ticket tracking.


## Priority Scheduling with Aging

The admin dashboard supports both FCFS and non-preemptive Priority + Aging. Priority levels use `1 = highest` and `4 = lowest`. Every 5 minutes a READY ticket waits, its effective priority improves by one level (the numeric value decreases), stopping at priority 1. At each dispatch point, the scheduler chooses the ready ticket with the best effective priority; ties go to the earlier arrival and then lower ticket ID. A running ticket is not preempted.

The Gantt chart shows every scheduled ticket in one shared horizontal timeline. Short segments display their queue order; hover over a segment to view the ticket ID, title, and interval.
