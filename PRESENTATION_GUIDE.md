# Phase 2 Presentation Guide (40% Prototype)

## 5–7 minute live demo

1. **Problem and goal (30–45 sec):** explain that campus support tickets are often tracked informally; this prototype centralizes requests and demonstrates OS scheduling.
2. **Submit a ticket (60 sec):** from Home, submit a new example request. Point out field validation and the generated `HD-xxxx` tracking number.
3. **Track the ticket (45 sec):** show status, ticket history, category, service estimate, and why the ETA is labelled approximate.
4. **Database layer (60 sec):** in MySQL Workbench, show `helpdesk_db` and tables `users`, `categories`, `tickets`, `ticket_history`, `scheduling_runs`, `scheduling_results`. Run `SELECT ticket_id, title, priority, status FROM tickets;` and `SELECT * FROM ticket_history ORDER BY history_id DESC;`.
5. **OS scheduler (90 sec):** go to Admin dashboard and run FCFS. Point out C++17 engine label; if it says Python fallback, fix compiler setup before the presentation.
6. **Gantt chart and metrics (60 sec):** explain arrival/service/start/completion and waiting/turnaround/response calculations. Mention single-lane, non-preemptive FCFS simulation.
7. **Integrity caveat (20 sec):** point out that a scheduling run changes estimates and saves the result but does not automatically resolve the actual ticket.

## Three-day preparation checklist

### Day 1 — Make it run
- Install Python dependencies and start the app.
- Confirm the home page, tracking page, and dashboard load.
- Configure MySQL mode and check tables if you will present the DBMS layer.
- Install/verify `g++`; rerun FCFS and confirm engine label says C++17 executable.

### Day 2 — Verify the workflow
- Submit two fresh tickets and track each one.
- Run FCFS multiple times and check that new `scheduling_runs` and `scheduling_results` records are saved.
- Restart Flask and verify ticket data persists.
- Practise explaining the FCFS formulas and why simulated completion is not a real resolution.

### Day 3 — Rehearse and protect the demo
- Reset and reseed the demo database once, then run the complete presentation path.
- Keep a short screen recording or screenshots as backup.
- Close unrelated apps and do not run the reset action after adding any data you need to keep.
- Avoid presenting a publicly deployed instance; this prototype has no production authentication.

## Useful MySQL checks

```sql
USE helpdesk_db;
SELECT status, COUNT(*) AS tickets FROM tickets GROUP BY status;
SELECT ticket_id, title, priority, status, arrival_offset, estimated_service_minutes FROM tickets ORDER BY arrival_offset, ticket_id;
SELECT * FROM scheduling_runs ORDER BY run_id DESC;
SELECT * FROM scheduling_results ORDER BY run_id DESC, queue_order;
```


## Priority + Aging demonstration
Run the **Priority + Aging** scheduler from the admin dashboard. Explain that priority 1 is highest and priority 4 is lowest. Every 5 minutes a ticket waits, its effective priority improves by one level, down to 1. The scheduler recalculates effective priority each time it chooses the next READY ticket; once a ticket starts, it runs to completion. The results table displays base priority, effective priority at dispatch, and aging boost.
