"""Isolated palette API/contrast checks; never edits production runtime data."""
import unittest
from test_course_rules_editor import DisposableServer, server


def luminance(value):
    channels = [int(value[i:i+2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))


def contrast(a, b):
    low, high = sorted((luminance(a), luminance(b)))
    return (high + .05) / (low + .05)


class PaletteTests(unittest.TestCase):
    def test_presets_keep_originals_and_add_nine_readable_palettes(self):
        presets = server.THEME_PRESETS
        self.assertEqual(len(presets), 20)
        self.assertEqual(len({p['id'] for p in presets}), 20)
        self.assertEqual(presets[0]['id'], 'clean-blue')
        palettes = [p for p in presets if 'inspiration' in p]
        self.assertEqual(len(palettes), 9)
        for p in palettes:
            with self.subTest(theme=p['id']):
                c, t = p['colors'], p['tokens']
                for a, b in [(c['text'], c['surface']), (t['muted'], c['surface']),
                             (c['text'], t['panel-2']), (t['muted'], t['panel-2']),
                             (t['button-text'], c['primary'])]:
                    self.assertGreaterEqual(contrast(a, b), 4.5)

    def test_all_new_presets_save_and_reload_in_disposable_config(self):
        service = DisposableServer()
        try:
            for p in server.THEME_PRESETS:
                with self.subTest(theme=p['id']):
                    reply = service.request('/api/theme/save', {'active': p['id']})
                    self.assertTrue(reply['ok'])
                    self.assertEqual(reply['theme']['active'], p['id'])
                    self.assertEqual(service.request('/api/theme')['active'], p['id'])
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
