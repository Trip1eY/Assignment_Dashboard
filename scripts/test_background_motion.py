"""Theme-motion compatibility and isolated persistence checks; no production data."""
import math
import unittest
from test_course_rules_editor import DisposableServer, server


class MotionNormalizationTest(unittest.TestCase):
    def test_old_config_and_independent_defaults(self):
        one = server.normalize_ui_theme({"active": "spiral-nebula"})
        two = server.normalize_ui_theme()
        self.assertEqual(one["motion"], server.DEFAULT_BACKGROUND_MOTION)
        one["motion"]["speed"] = 2
        self.assertEqual(two["motion"]["speed"], 1)
        self.assertEqual(server.DEFAULT_UI_THEME["motion"]["speed"], 1)

    def test_bounds_and_validation(self):
        self.assertEqual(server.normalize_background_motion({"enabled": False, "mode": "stars", "intensity": 150, "speed": -2}),
                         {"enabled": False, "mode": "stars", "intensity": 100, "speed": .25})
        for invalid in (None, [], "bad", {"enabled": "false", "mode": {}, "intensity": True, "speed": "2"},
                        {"intensity": math.inf, "speed": math.nan}):
            self.assertEqual(server.normalize_background_motion(invalid), server.DEFAULT_BACKGROUND_MOTION)

    def test_all_presets_preserve_options(self):
        motion = {"enabled": True, "mode": "peach", "intensity": 41, "speed": 1.35}
        for preset in server.THEME_PRESETS:
            theme = server.normalize_ui_theme({"active": preset["id"], "motion": motion})
            self.assertEqual(theme["active"], preset["id"])
            self.assertEqual(theme["motion"], motion)


class MotionPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.service = DisposableServer()

    def tearDown(self):
        self.service.close()

    def test_save_reload_and_classic_compatibility(self):
        original = self.service.request('/api/theme')
        motion = {"enabled": False, "mode": "stars", "intensity": 37, "speed": 1.75}
        saved = self.service.request('/api/theme/save', {**original, "active": "apricot-stars", "motion": motion})
        self.assertTrue(saved["ok"])
        self.assertEqual(self.service.request('/api/theme')["motion"], motion)
        self.assertEqual(server.load_config_raw()["ui_theme"]["motion"], motion)
        legacy = self.service.request('/api/theme/save', {"active": "clean-blue"})
        self.assertEqual(legacy["theme"]["motion"], motion)
        self.assertEqual(legacy["theme"]["active"], "clean-blue")


if __name__ == '__main__':
    unittest.main()
