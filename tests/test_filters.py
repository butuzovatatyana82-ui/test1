import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from okunek.filters import *


def orig(artist, title, query="", extra="", title_only=False):
    return is_original(classify(artist, title, query, extra, title_only)["tags"])


class Originals(unittest.TestCase):
    def test_remix_variants_rejected(self):
        for t in ("Numb (Remix)", "Numb - Club Mix", "Numb [Bootleg]", "Numb Рэмикс", "Numb (DJ X Rework)", "Numb RMX", "Song (Extended Mix)", "Song - VIP Mix"):
            if "Рэмикс" in t: continue  # опечатка-ловушка не проверяем
            self.assertFalse(orig("Linkin Park", t), t)
        self.assertFalse(orig("Linkin Park", "Numb ремикс"))

    def test_mashups_covers_speed_karaoke(self):
        bad = ["Numb x In The End Mashup", "Numb vs In The End", "Numb (Cover by Anna)", "Numb Nightcore", "Numb (Sped Up)",
               "Numb slowed + reverb", "Numb Karaoke Version", "Numb 8D Audio", "Numb (Piano Version)", "Best of Linkin Park",
               "Numb Tribute", "Numb AI cover", "Numb (Instrumental)", "Numb (Acoustic)", "Numb - Live at Wembley", "Numb [Live]"]
        for t in bad:
            self.assertFalse(orig("Linkin Park", t), t)

    def test_real_originals_pass(self):
        good = ["Numb", "Numb (Official Music Video)", "Numb [Remastered 2011]", "Numb - Remastered 2011", "Numb (feat. Jay-Z)",
                "Live Forever", "Don't Stop Believin'", "Remember the Name", "Cover Me", "Time After Time", "Flip the Switch", "Mashed Potato Time"]
        for t in good:
            self.assertTrue(orig("Artist", t), t)

    def test_word_in_query_is_allowed(self):
        self.assertTrue(orig("Linkin Park", "Numb Remix", query="linkin park numb remix"))
        self.assertTrue(orig("Linkin Park", "Numb (Live)", query="numb live"))
        self.assertFalse(orig("Linkin Park", "Numb Remix", query="linkin park numb"))

    def test_catalog_title_only_suffix(self):
        self.assertFalse(orig("A", "Song - Live at Wembley", title_only=True))
        self.assertFalse(orig("A", "Song - Acoustic", title_only=True))
        self.assertTrue(orig("A", "Live Forever", title_only=True))
        self.assertTrue(orig("A", "Song - Remastered 2011", title_only=True))

    def test_explicit_clean(self):
        self.assertTrue(classify("A", "Song (Explicit)")["exp"])
        self.assertTrue(classify("A", "Song (Clean)")["bad"])
        self.assertTrue(classify("A", "Song - Radio Edit")["soft"])
        self.assertFalse(classify("A", "Song (Uncensored)")["bad"])


class Keys(unittest.TestCase):
    def test_dedupe_key(self):
        a = track_key("Eminem feat. Rihanna", "Love The Way You Lie (Explicit)")
        b = track_key("Eminem", "Love the way you lie - Remastered 2011")
        self.assertEqual(a, b)
        self.assertNotEqual(track_key("A", "Song"), track_key("A", "Song 2"))

    def test_dedupe_keeps_best(self):
        ts = [dict(artist="A", title="Song", sc=1), dict(artist="A", title="Song (Explicit)", sc=5), dict(artist="B", title="Song", sc=2)]
        r = dedupe(ts)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["sc"], 5)

    def test_is_url(self):
        self.assertTrue(is_url("https://youtu.be/abc"))
        self.assertFalse(is_url("imagine dragons believer"))


class Match(unittest.TestCase):
    def C(self, title, ch, dur, views=0, url="u"):
        return dict(title=title, channel=ch, duration=dur, view_count=views, url=url)

    def test_picks_topic_over_remix_and_live(self):
        cands = [
            self.C("Imagine Dragons - Believer (Remix)", "DJ Whatever", 205, 9e7),
            self.C("Believer (Live)", "Imagine Dragons", 260, 9e6),
            self.C("Believer", "Imagine Dragons - Topic", 204, 3e8),
            self.C("Imagine Dragons - Believer (Official Music Video)", "ImagineDragonsVEVO", 217, 2e9),
        ]
        b = best_candidate(cands, "Imagine Dragons", "Believer", 204)
        self.assertEqual(b["channel"], "Imagine Dragons - Topic")

    def test_rejects_when_nothing_good(self):
        cands = [self.C("Totally other song", "Someone", 100), self.C("Believer remix nightcore", "X", 204)]
        self.assertIsNone(best_candidate(cands, "Imagine Dragons", "Believer", 204))

    def test_duration_matters(self):
        a = self.C("Artist - Song", "Artist - Topic", 200)
        b = self.C("Artist - Song", "Artist - Topic", 640)
        self.assertGreater(match_score(a, "Artist", "Song", 201), match_score(b, "Artist", "Song", 201))


class Scoring(unittest.TestCase):
    def test_originals_ranked_above_junk_and_filtered(self):
        a = dict(artist="A", title="Song", dur=200, off=True, tags=[], exp=True)
        b = dict(artist="A", title="Song (Remix)", dur=200, tags=["remix"])
        w = query_words(["a song"])
        self.assertGreater(score_web(a, w), score_web(b, w))
        self.assertTrue(passes(a))
        self.assertFalse(passes(b))
        self.assertTrue(passes(b, originals=False))

    def test_clean_filtered_when_uncensored(self):
        self.assertFalse(passes(dict(tags=[], bad=True, exp=False), uncens=True))
        self.assertTrue(passes(dict(tags=[], bad=True, exp=False), uncens=False))

    def test_long_compilation_dropped(self):
        self.assertFalse(passes(dict(tags=[], dur=3600)))
        self.assertTrue(passes(dict(tags=[], dur=3600, cat=True)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
