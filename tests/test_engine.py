import os, sys, tempfile, unittest
os.environ["HOME"] = tempfile.mkdtemp(); os.environ["APPDATA"] = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest import mock
from okunek import engine, net, filters as flt


def cand(title, ch, dur, views=0, url=None):
    return dict(title=title, channel=ch, duration=dur, view_count=views, url=url or "https://youtu.be/" + title[:6].replace(" ", ""))


class Catalog(unittest.TestCase):
    T = dict(kind="cat", src="dz:42", artist="Imagine Dragons", title="Believer", dur=204)

    def test_match_prefers_original_topic(self):
        res = [cand("Believer (Nightcore)", "NC", 150, 5e7, "u1"), cand("Believer", "Imagine Dragons - Topic", 204, 3e8, "u2"),
               cand("Believer remix", "DJ", 210, 9e8, "u3")]
        with mock.patch.object(engine, "flat_search", return_value=res):
            m = engine.match_catalog(dict(self.T, src="dz:m1"))
        self.assertEqual(m["url"], "u2")

    def test_match_falls_back_to_soundcloud_and_caches(self):
        calls = []
        def fs(prov, q, n):
            calls.append(prov)
            return [cand("Totally different", "x", 99)] if prov == "ytsearch" else [cand("Imagine Dragons - Believer", "Imagine Dragons", 205, 10, "sc1")]
        with mock.patch.object(engine, "flat_search", side_effect=fs):
            m = engine.match_catalog(dict(self.T, src="dz:m2"))
            m2 = engine.match_catalog(dict(self.T, src="dz:m2"))
        self.assertEqual(m["url"], "sc1"); self.assertEqual(m2, m); self.assertEqual(calls, ["ytsearch", "scsearch"])

    def test_resolve_catalog_only_remixes_gives_clear_error(self):
        with mock.patch.object(engine, "flat_search", return_value=[cand("Believer remix", "DJ", 204, 9, "r")]):
            with self.assertRaises(RuntimeError) as c:
                engine.resolve(dict(self.T, src="dz:m3"))
        self.assertIn("оригинальную", str(c.exception))

    def test_resolve_web_falls_back_to_other_source(self):
        t = dict(kind="web", src="https://www.youtube.com/watch?v=aaa", artist="A", title="Song", dur=200)
        def stream(page, alive):
            if "youtube" in page: raise RuntimeError("403")
            return "http://audio", {}
        with mock.patch.object(engine, "_stream", side_effect=stream), \
             mock.patch.object(engine, "flat_search", return_value=[cand("A - Song", "A", 201, 5, "https://soundcloud.com/a/song")]):
            self.assertEqual(engine.resolve(t)[0], "http://audio")


class Deez(unittest.TestCase):
    def test_all_tracks_dedupes_and_drops_junk_and_foreign(self):
        d = net.Deezer()
        albums = [dict(id=1, title="Album", cover="c", date="2020", type="album", exp=False),
                  dict(id=2, title="Deluxe", cover="c", date="2021", type="album", exp=False)]
        tr = lambda i, title, aid=5: dict(id=i, title=title, duration=200, artist=dict(id=aid, name="A"), rank=i)
        data = {1: [tr(1, "Song"), tr(2, "Other (Remix)"), tr(3, "Feat track", aid=99)], 2: [tr(4, "Song - Remastered 2011"), tr(5, "New")]}
        with mock.patch.object(net.Deezer, "_get", side_effect=lambda path, **k: {"data": data[int(path.split("/")[2])]}), \
             mock.patch.object(net, "cache_get", return_value=None), mock.patch.object(net, "cache_put"):
            r = d.all_tracks(5, albums)
        self.assertEqual(sorted(t["title"] for t in r), ["New", "Song - Remastered 2011"])  # ремикс и чужой фит отброшены, дубль схлопнут

    def test_albums_collapse_editions_and_drop_tribute(self):
        d = net.Deezer()
        raw = [dict(id=1, title="Album", cover_medium="c", release_date="2020-01-01", record_type="album", explicit_lyrics=False),
               dict(id=2, title="Album (Deluxe)", cover_medium="c", release_date="2021-01-01", record_type="album", explicit_lyrics=False),
               dict(id=3, title="Tribute to A", cover_medium="c", release_date="2019-01-01", record_type="album", explicit_lyrics=False),
               dict(id=4, title="Single", cover_medium="c", release_date="2022-01-01", record_type="single", explicit_lyrics=False)]
        with mock.patch.object(net.Deezer, "_get", return_value={"data": raw}), mock.patch.object(net, "cache_get", return_value=None), mock.patch.object(net, "cache_put"):
            r = d.albums(5)
        self.assertEqual(sorted(a["title"] for a in r), ["Album (Deluxe)", "Single"])
        self.assertNotIn("Tribute to A", [a["title"] for a in r])
        self.assertEqual(len([a for a in r if a["type"] == "album"]), 1)


class Upd(unittest.TestCase):
    def test_versions(self):
        from okunek.updater import vtuple
        self.assertTrue(vtuple("v3.1.0") > vtuple("3.0.9")); self.assertTrue(vtuple("3.10.0") > vtuple("3.9.9"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
