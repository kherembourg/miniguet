import base64, json, os, tempfile, threading, time, unittest

import voice
from voice import MAX_BYTES, VoiceError, available, conf, transcribe
from tests.fakes import FakeHandler, FakeSrv

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_ENV = ("FAKE_SLEEP", "FAKE_FFMPEG_SLEEP", "FAKE_WHISPER_SLEEP", "FAKE_PIDFILE")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.scratch = os.path.join(self.tmp.name, "scratch")
        os.mkdir(self.scratch, 0o700)
        model = os.path.join(self.tmp.name, "model.bin")
        open(model, "w").close()
        self.c = {"bin": os.path.join(HERE, "fake_whisper.sh"), "ffmpeg": os.path.join(HERE, "fake_ffmpeg.sh"), "model": model}
        for k in FAKE_ENV:
            os.environ.pop(k, None)
            self.addCleanup(os.environ.pop, k, None)


class VoiceTest(Base):
    def test_transcribe_returns_text(self):
        self.assertEqual(transcribe(b"audio", self.c, self.scratch), "bonjour le monde")
        self.assertEqual(os.listdir(self.scratch), [])

    def test_transcribe_rejects_too_big(self):
        with self.assertRaises(VoiceError):
            transcribe(b"x" * (MAX_BYTES + 1), self.c, self.scratch)
        self.assertEqual(os.listdir(self.scratch), [])

    def test_transcribe_deadline_is_shared(self):
        os.environ["FAKE_SLEEP"] = "0.8"   # ffmpeg 0.8 s then whisper 0.8 s: two separate 1 s timeouts would let 1.6 s through
        t = time.monotonic()
        with self.assertRaises(VoiceError) as cm:
            transcribe(b"audio", self.c, self.scratch, timeout=1)
        self.assertLess(time.monotonic() - t, 1.3)
        self.assertIn("délai", str(cm.exception))
        self.assertEqual(os.listdir(self.scratch), [])

    def test_transcribe_concurrent_refused(self):
        os.environ["FAKE_SLEEP"] = "0.5"
        first = threading.Thread(target=transcribe, args=(b"audio", self.c, self.scratch))
        first.start()
        time.sleep(0.2)
        t = time.monotonic()
        with self.assertRaises(VoiceError) as cm:
            transcribe(b"audio", self.c, self.scratch)
        self.assertLess(time.monotonic() - t, 0.1)
        self.assertIn("déjà en cours", str(cm.exception))
        first.join()
        self.assertEqual(transcribe(b"audio", self.c, self.scratch), "bonjour le monde")   # the lock was released

    def test_transcribe_cleans_up_and_kills_on_deadline(self):
        pidfile = os.path.join(self.tmp.name, "pid")
        os.environ["FAKE_WHISPER_SLEEP"] = "5"
        os.environ["FAKE_PIDFILE"] = pidfile
        with self.assertRaises(VoiceError):
            transcribe(b"audio", self.c, self.scratch, timeout=1)
        self.assertEqual(os.listdir(self.scratch), [])
        with open(pidfile) as f:
            with self.assertRaises(ProcessLookupError):
                os.kill(int(f.read()), 0)

    def test_transcribe_missing_binary(self):
        c = dict(self.c, bin="/nope")
        self.assertFalse(available(c))
        with self.assertRaises(VoiceError):
            transcribe(b"audio", c, self.scratch)
        self.assertEqual(os.listdir(self.scratch), [])

    def test_conf_merges_whisper_json(self):
        with open(os.path.join(self.tmp.name, "whisper.json"), "w") as f:
            json.dump({"bin": "~/mon-whisper"}, f)
        c = conf(self.tmp.name)
        self.assertEqual(c["bin"], os.path.expanduser("~/mon-whisper"))
        self.assertTrue(c["model"].endswith("ggml-large-v3-turbo-q5_0.bin"))
        self.assertNotIn("~", c["model"])


class RouteTest(Base):
    def srv(self):
        srv = FakeSrv()
        with open(os.path.join(srv.STATE_DIR, "whisper.json"), "w") as f:
            json.dump(self.c, f)
        voice.register(srv)
        return srv

    def post(self, srv, d, paired=True):
        return json.loads(srv.ROUTES["POST"]["/api/transcribe"](FakeHandler("/api/transcribe", paired), json.dumps(d))[2])

    def test_route_voice_available(self):
        srv = self.srv()
        self.assertEqual(json.loads(srv.ROUTES["GET"]["/api/voice"](FakeHandler("/api/voice"), "")[2]), {"available": True})

    def test_route_returns_text(self):
        srv = self.srv()
        r = self.post(srv, {"audio": base64.b64encode(b"audio").decode(), "type": "audio/mp4"})
        self.assertEqual(r, {"text": "bonjour le monde"})

    def test_route_requires_pairing(self):
        srv = self.srv()
        r = self.post(srv, {"audio": base64.b64encode(b"audio").decode()}, paired=False)
        self.assertIn("non appairé", r["error"])
        self.assertEqual(os.listdir(srv.SCRATCH), [])

    def test_route_rejects_oversized_body(self):
        srv = self.srv()
        r = self.post(srv, {"audio": "A" * (((MAX_BYTES + 2) // 3) * 4 + 4)})
        self.assertIn("trop gros", r["error"])
        self.assertEqual(os.listdir(srv.SCRATCH), [])

    def test_route_reports_voice_errors(self):
        srv = self.srv()
        os.environ["FAKE_SLEEP"] = "0"
        r = self.post(srv, {"audio": "pas du base64 !"})
        self.assertIn("error", r)


if __name__ == "__main__":
    unittest.main()
