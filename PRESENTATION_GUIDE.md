# Phase 3 Presentation Guide — Multi-Organization IT Help Desk

## Suggested 8–10 minute demonstration

1. **Project purpose (30 sec):** explain that the platform centralizes IT support tickets for multiple client organizations and combines practical service workflows with queue scheduling, concurrency and structured data management concepts.
2. **Submit and track a ticket (60 sec):** choose an organization and service category, submit a ticket, save its `HD-xxxx` ID, and show the requester-email match used for tracking.
3. **Administrator sign-in (30 sec):** sign in with the password configured in `.env`. Show organization, ticket, technician, and resource management.
4. **Scheduling engine (2 min):** run FCFS and Priority + Aging, then run Round Robin with a visible time quantum (for example, 00:04). Explain that RR is a simulation of preemptive process scheduling, not an instruction to interrupt real technicians at fixed intervals.
5. **Gantt chart and metrics (1 min):** point out that RR tickets can appear in multiple segments. Explain waiting, turnaround, response, completion, throughput, CPU utilization, and context switches. Note that estimates do not resolve tickets.
6. **Ticket assignment and technician workflow (1 min):** create a technician, assign an open ticket, sign in as that technician, move it to In Progress, then resolve it with a short resolution note.
7. **Separate ratings (1 min):** track the resolved ticket and submit the service rating plus an optional technician rating. Show that technician ratings are admin-only while `/services` shows aggregate service-category ratings and review counts.
8. **Organizations and isolation (45 sec):** register a second organization and show that new tickets can be associated with it. Explain that full production multi-tenant security requires customer accounts or organization-approved invitations; the current demo uses requester email matching.
9. **Resource allocation (1 min):** add a resource, declare a technician maximum claim, request an allocation, and explain how Banker's Algorithm checks the safe state. Release the allocation.
10. **Database and reporting evidence (1 min):** in MySQL Workbench: show organizations, tickets, assignments, ratings, scheduling runs/results/segments, resources, and allocations. Demonstrate a join or aggregation query.

## Useful MySQL queries

```sql
USE helpdesk_db;

-- Ticket volume by organization and status
SELECT o.organization_name, t.status, COUNT(*) AS ticket_count
FROM tickets t
JOIN organizations o ON o.organization_id = t.organization_id
GROUP BY o.organization_name, t.status
ORDER BY o.organization_name, t.status;

-- Technician performance (internal/admin reporting)
SELECT te.name, ROUND(AVG(tr.rating), 2) AS average_rating,
       COUNT(tr.rating_id) AS rating_count
FROM technicians te
LEFT JOIN technician_ratings tr ON tr.technician_id = te.technician_id
GROUP BY te.technician_id, te.name
ORDER BY average_rating DESC;

-- Service-category performance (aggregate/client-facing)
SELECT c.category_name, ROUND(AVG(sr.rating), 2) AS average_rating,
       COUNT(sr.rating_id) AS review_count
FROM categories c
LEFT JOIN service_ratings sr ON sr.category_id = c.category_id
GROUP BY c.category_id, c.category_name
ORDER BY average_rating DESC;

-- Latest Round Robin runs and their context-switch settings
SELECT run_id, algorithm, time_quantum, context_switches,
       context_switch_overhead, ticket_count, avg_waiting_time,
       avg_response_time, avg_turnaround_time
FROM scheduling_runs
WHERE algorithm = 'Round Robin'
ORDER BY run_id DESC;

-- Individual Round Robin execution segments
SELECT sr.run_id, sr.ticket_id, sg.segment_number,
       sg.start_time, sg.end_time
FROM scheduling_results sr
JOIN scheduling_segments sg ON sg.result_id = sr.result_id
ORDER BY sr.run_id DESC, sr.queue_order, sg.segment_number;
```

## Important demo precautions

- Change `SECRET_KEY` and `ADMIN_PASSWORD` in `.env` before using the app on a shared network.
- Do not use Reset Demo on records you need to keep; it removes ticket, history, scheduling, rating, assignment, and allocation data.
- Make sure the latest run displays `C++17 Round Robin executable` when demonstrating the C++ scheduler. A clearly labelled Python fallback is provided if no compiler is available.
- Ratings are currently matched using ticket ID and requester email; this is not email OTP verification.
- Keep the demonstration on localhost or a trusted lab network. Do not describe the current prototype as production-ready tenant authentication.
