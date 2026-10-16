# Updates in this version

- The Gantt chart displays all scheduled tickets on one shared horizontal timeline, with horizontal scrolling on narrow screens.
- Both FCFS and Priority + Aging are available in the admin dashboard.
- Priority scale: 1 is highest, 4 is lowest.
- Aging interval: every 5 minutes spent waiting improves effective priority by one level, down to priority 1.
- Scheduling is non-preemptive: once a ticket starts, it runs to completion.
- The scheduling result table shows base priority, effective priority at dispatch, and aging boost.
- Existing database schema is retained; the run algorithm and notes are stored in the existing scheduling_runs table.

Run tests with: `python -m unittest -v tests_scheduler.py`
