"""Small standard-library tests for the FCFS integration (no pytest needed)."""
import unittest
from scheduler_bridge import run_fcfs, run_priority_aging


class FCFSTests(unittest.TestCase):
    def test_arrival_then_ticket_id_order_and_metrics(self):
        jobs = [
            {"ticket_id": 4, "arrival_offset": 0, "estimated_service_minutes": 7, "priority": 3},
            {"ticket_id": 2, "arrival_offset": 0, "estimated_service_minutes": 5, "priority": 1},
            {"ticket_id": 3, "arrival_offset": 2, "estimated_service_minutes": 3, "priority": 2},
        ]
        rows, engine = run_fcfs(jobs)
        self.assertEqual([r["ticket_id"] for r in rows], [2, 4, 3])
        self.assertEqual(rows[0]["start_time"], 0)
        self.assertEqual(rows[0]["completion_time"], 5)
        self.assertEqual(rows[0]["waiting_time"], 0)
        self.assertEqual(rows[1]["start_time"], 5)
        self.assertEqual(rows[1]["completion_time"], 12)
        self.assertEqual(rows[1]["waiting_time"], 5)
        self.assertEqual(rows[2]["start_time"], 12)
        self.assertEqual(rows[2]["completion_time"], 15)
        self.assertEqual(rows[2]["turnaround_time"], 13)
        self.assertTrue(engine)

    def test_idle_time_before_first_arrival(self):
        jobs = [{"ticket_id": 1, "arrival_offset": 5, "estimated_service_minutes": 4, "priority": 2}]
        rows, _ = run_fcfs(jobs)
        self.assertEqual(rows[0]["start_time"], 5)
        self.assertEqual(rows[0]["completion_time"], 9)
        self.assertEqual(rows[0]["waiting_time"], 0)

    def test_invalid_service_time_rejected(self):
        jobs = [{"ticket_id": 1, "arrival_offset": 0, "estimated_service_minutes": 0, "priority": 1}]
        with self.assertRaises(ValueError):
            run_fcfs(jobs)

    def test_priority_aging_promotes_a_long_waiting_low_priority_ticket(self):
        jobs = [
            {"ticket_id": 1, "arrival_offset": 0, "estimated_service_minutes": 10, "priority": 1},
            {"ticket_id": 2, "arrival_offset": 0, "estimated_service_minutes": 2, "priority": 4},
            {"ticket_id": 3, "arrival_offset": 9, "estimated_service_minutes": 1, "priority": 3},
        ]
        rows, engine = run_priority_aging(jobs, aging_interval=5)
        self.assertEqual([row["ticket_id"] for row in rows], [1, 2, 3])
        self.assertEqual(rows[1]["waiting_time"], 10)
        self.assertEqual(rows[2]["start_time"], 12)
        self.assertTrue(engine)

    def test_priority_aging_can_change_fcfs_order(self):
        jobs = [
            {"ticket_id": 1, "arrival_offset": 0, "estimated_service_minutes": 10, "priority": 1},
            {"ticket_id": 2, "arrival_offset": 1, "estimated_service_minutes": 5, "priority": 4},
            {"ticket_id": 3, "arrival_offset": 2, "estimated_service_minutes": 15, "priority": 2},
        ]
        fcfs, _ = run_fcfs(jobs)
        aged, _ = run_priority_aging(jobs, aging_interval=5)
        self.assertEqual([row["ticket_id"] for row in fcfs], [1, 2, 3])
        self.assertEqual([row["ticket_id"] for row in aged], [1, 3, 2])

    def test_priority_aging_rejects_invalid_interval(self):
        with self.assertRaises(ValueError):
            run_priority_aging([], aging_interval=0)

    def test_empty_input(self):
        rows, _ = run_fcfs([])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
