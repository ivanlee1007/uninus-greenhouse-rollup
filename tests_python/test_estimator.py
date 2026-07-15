import unittest

from custom_components.uninus_greenhouse_rollup.estimator import (
    CONFIDENCE_CALIBRATED,
    CONFIDENCE_ESTIMATED,
    CONFIDENCE_UNKNOWN,
    RollupEstimator,
)


class RollupEstimatorTest(unittest.TestCase):
    def test_partial_open_then_stop_freezes_estimated_position(self):
        estimator = RollupEstimator(100, 120, position=20, confidence=CONFIDENCE_CALIBRATED)
        estimator.sync(open_on=True, close_on=False, now=10)
        estimator.sync(open_on=False, close_on=False, now=40)

        self.assertAlmostEqual(estimator.position, 50)
        self.assertEqual(estimator.confidence, CONFIDENCE_ESTIMATED)
        self.assertEqual(estimator.command_state, "idle")

    def test_open_clamps_at_endpoint_while_relay_remains_on(self):
        estimator = RollupEstimator(100, 100, position=80, confidence=CONFIDENCE_ESTIMATED)
        estimator.sync(open_on=True, close_on=False, now=0)
        estimator.advance(30)

        self.assertEqual(estimator.position, 100)
        self.assertEqual(estimator.confidence, CONFIDENCE_CALIBRATED)
        self.assertEqual(estimator.command_state, "opening_timer")
        self.assertFalse(estimator.is_opening)

    def test_close_clamps_at_zero(self):
        estimator = RollupEstimator(100, 80, position=25, confidence=CONFIDENCE_ESTIMATED)
        estimator.sync(open_on=False, close_on=True, now=5)
        estimator.advance(30)

        self.assertEqual(estimator.position, 0)
        self.assertEqual(estimator.confidence, CONFIDENCE_CALIBRATED)
        self.assertEqual(estimator.command_state, "closing_timer")
        self.assertFalse(estimator.is_closing)

    def test_unknown_position_calibrates_only_after_full_travel(self):
        estimator = RollupEstimator(60, 70)
        estimator.sync(open_on=True, close_on=False, now=0)
        estimator.advance(30)
        self.assertIsNone(estimator.position)
        self.assertEqual(estimator.confidence, CONFIDENCE_UNKNOWN)

        estimator.advance(60)
        self.assertEqual(estimator.position, 100)
        self.assertEqual(estimator.confidence, CONFIDENCE_CALIBRATED)

    def test_unknown_partial_run_stays_unknown_after_stop(self):
        estimator = RollupEstimator(60, 70)
        estimator.sync(open_on=False, close_on=True, now=0)
        estimator.sync(open_on=False, close_on=False, now=20)

        self.assertIsNone(estimator.position)
        self.assertEqual(estimator.confidence, CONFIDENCE_UNKNOWN)

    def test_both_relays_on_reports_conflict_and_does_not_move(self):
        estimator = RollupEstimator(100, 100, position=40, confidence=CONFIDENCE_ESTIMATED)
        estimator.sync(open_on=True, close_on=True, now=10)
        estimator.advance(80)

        self.assertEqual(estimator.position, 40)
        self.assertEqual(estimator.command_state, "conflict")
        self.assertFalse(estimator.is_opening)
        self.assertFalse(estimator.is_closing)

    def test_restored_position_can_continue_after_restart(self):
        estimator = RollupEstimator.from_snapshot(
            100,
            120,
            {"position": 35, "confidence": CONFIDENCE_ESTIMATED},
        )
        estimator.sync(open_on=True, close_on=False, now=200)
        estimator.sync(open_on=False, close_on=False, now=220)

        self.assertEqual(estimator.position, 55)
        self.assertEqual(estimator.confidence, CONFIDENCE_ESTIMATED)

    def test_stale_timestamp_is_ignored(self):
        estimator = RollupEstimator(100, 100, position=10, confidence=CONFIDENCE_ESTIMATED)
        estimator.sync(open_on=True, close_on=False, now=100)
        estimator.advance(120)
        estimator.advance(110)

        self.assertEqual(estimator.position, 30)

    def test_malformed_snapshot_falls_back_to_unknown(self):
        for snapshot in (
            {"position": "not-a-number", "confidence": CONFIDENCE_ESTIMATED},
            {"position": "42", "confidence": CONFIDENCE_ESTIMATED},
            {"position": True, "confidence": CONFIDENCE_CALIBRATED},
            {"position": 150, "confidence": CONFIDENCE_CALIBRATED},
            {"position": -20, "confidence": CONFIDENCE_CALIBRATED},
            {"position": [], "confidence": CONFIDENCE_ESTIMATED},
            {"position": float("nan"), "confidence": CONFIDENCE_CALIBRATED},
            {"position": 42, "confidence": "bogus"},
        ):
            with self.subTest(snapshot=snapshot):
                estimator = RollupEstimator.from_snapshot(100, 100, snapshot)
                self.assertIsNone(estimator.position)
                self.assertEqual(estimator.confidence, CONFIDENCE_UNKNOWN)

    def test_snapshot_is_json_serializable_state(self):
        estimator = RollupEstimator(100, 100, position=75, confidence=CONFIDENCE_CALIBRATED)
        self.assertEqual(
            estimator.snapshot(),
            {"position": 75.0, "confidence": CONFIDENCE_CALIBRATED},
        )


if __name__ == "__main__":
    unittest.main()
