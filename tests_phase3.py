"""Focused tests for the Phase 3 Round Robin scheduler."""
import unittest

from scheduler_bridge import _python_round_robin, run_round_robin


class RoundRobinTests(unittest.TestCase):
    def setUp(self):
        self.jobs = [
            {"ticket_id": 1, "arrival_offset": 0, "estimated_service_minutes": 10},
            {"ticket_id": 2, "arrival_offset": 0, "estimated_service_minutes": 5},
            {"ticket_id": 3, "arrival_offset": 0, "estimated_service_minutes": 8},
        ]

    def test_round_robin_segments_and_metrics(self):
        results, engine, switches = run_round_robin(self.jobs, quantum=4)
        by_id = {row["ticket_id"]: row for row in results}
        self.assertEqual(len(results), 3)
        self.assertEqual(by_id[1]["segments"], [
            {"start_time": 0, "end_time": 4},
            {"start_time": 12, "end_time": 16},
            {"start_time": 21, "end_time": 23},
        ])
        self.assertEqual(by_id[1]["completion_time"], 23)
        self.assertEqual(by_id[1]["waiting_time"], 13)
        self.assertEqual(by_id[1]["response_time"], 0)
        self.assertEqual(by_id[2]["completion_time"], 17)
        self.assertEqual(by_id[2]["waiting_time"], 12)
        self.assertEqual(by_id[3]["completion_time"], 21)
        self.assertEqual(switches, 6)
        self.assertTrue("Round Robin" in engine)

    def test_new_arrival_is_added_before_expired_job_is_requeued(self):
        jobs = [
            {"ticket_id": 11, "arrival_offset": 0, "estimated_service_minutes": 6},
            {"ticket_id": 12, "arrival_offset": 2, "estimated_service_minutes": 1},
        ]
        results, _ = _python_round_robin(jobs, quantum=3)
        by_id = {row["ticket_id"]: row for row in results}
        self.assertEqual(by_id[11]["segments"][0], {"start_time": 0, "end_time": 3})
        self.assertEqual(by_id[12]["segments"][0], {"start_time": 3, "end_time": 4})
        self.assertEqual(by_id[11]["segments"][1], {"start_time": 4, "end_time": 7})

    def test_arrival_idle_time_is_preserved(self):
        jobs = [{"ticket_id": 20, "arrival_offset": 7, "estimated_service_minutes": 2}]
        results, _ = _python_round_robin(jobs, quantum=4)
        self.assertEqual(results[0]["segments"], [{"start_time": 7, "end_time": 9}])
        self.assertEqual(results[0]["response_time"], 0)
        self.assertEqual(results[0]["waiting_time"], 0)

    def test_context_switch_overhead_is_counted_as_waiting(self):
        results, _, switches = run_round_robin(self.jobs, quantum=4, context_switch_overhead=1)
        by_id = {row["ticket_id"]: row for row in results}
        self.assertEqual(switches, 6)
        self.assertGreater(by_id[1]["completion_time"], 23)
        self.assertGreater(by_id[1]["waiting_time"], 13)

    def test_invalid_parameters_rejected(self):
        with self.assertRaises(ValueError):
            run_round_robin(self.jobs, quantum=0)
        with self.assertRaises(ValueError):
            run_round_robin(self.jobs, quantum=4, context_switch_overhead=31)

    def test_empty_input(self):
        results, _, switches = run_round_robin([], quantum=4)
        self.assertEqual(results, [])
        self.assertEqual(switches, 0)


if __name__ == "__main__":
    unittest.main()
