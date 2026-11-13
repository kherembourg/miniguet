"""Server tests on the demo mode: the real server.py runs in a subprocess on a free port, with MINIGUET_DEMO
pointing at a temporary copy of demo/. Paths are sent raw (http.client does not normalise them)."""
import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DemoServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="miniguet-demo-")
        cls.demo = os.path.join(cls.tmp, "demo")
        shutil.copytree(os.path.join(ROOT, "demo"), cls.demo, ignore=shutil.ignore_patterns("state", "out.log"))
        cls.port = free_port()
        cls.logf = open(os.path.join(cls.tmp, "server.log"), "w")
        env = dict(os.environ, MINIGUET_DEMO=cls.demo)
        cls.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(cls.port)],
                                    cwd=ROOT, env=env, stdout=cls.logf, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
                break
            except OSError:
                if cls.proc.poll() is not None:
                    break
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        cls.logf.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            c.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            r = c.getresponse()
            return r.status, r.getheader("Content-Type") or "", r.read()
        finally:
            c.close()

    def get_json(self, path):
        code, _, body = self.req("GET", path)
        self.assertEqual(code, 200, body[:200])
        return json.loads(body)

    def post_json(self, path, obj):
        code, _, body = self.req("POST", path, json.dumps(obj))
        self.assertEqual(code, 200, body[:200])
        return json.loads(body)

    def server_log(self):
        self.logf.flush()
        with open(self.logf.name) as f:
            return f.read()


class AssetsTest(DemoServer):
    def setUp(self):
        self.cleanup = []

    def tearDown(self):
        for p in self.cleanup:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            elif os.path.lexists(p):
                os.remove(p)

    def test_dotdot_that_stays_inside_assets_is_served(self):
        self.assertEqual(self.req("GET", "/assets/ui-sdk/x/../../logo.png")[0], 200)

    def test_nested_file_is_served_with_its_type(self):
        d = os.path.join(ROOT, "assets", "_t_nested_%d" % os.getpid())
        os.makedirs(os.path.join(d, "web", "chunks"))
        self.cleanup.append(d)
        for rel, data in (("web/chunks/a.js", b"export const a = 1"), ("web/s.css", b"@layer x;")):
            with open(os.path.join(d, rel), "wb") as f:
                f.write(data)
        base = "/assets/" + os.path.basename(d)
        code, ct, body = self.req("GET", base + "/web/chunks/a.js")
        self.assertEqual((code, ct.split(";")[0], body), (200, "text/javascript", b"export const a = 1"))
        code, ct, _ = self.req("GET", base + "/web/s.css")
        self.assertEqual((code, ct), (200, "text/css; charset=utf-8"))

    def outside_png(self):
        p = os.path.join(ROOT, "_outside_%d.png" % os.getpid())   # served extension, but outside assets/
        with open(p, "wb") as f:
            f.write(b"\x89PNG-outside")
        self.cleanup.append(p)
        return os.path.basename(p)

    def test_dotdot_out_of_assets_is_refused(self):
        name = self.outside_png()
        self.assertEqual(self.req("GET", "/assets/../" + name)[0], 404)

    def test_encoded_dotdot_out_of_assets_is_refused(self):
        name = self.outside_png()
        self.assertEqual(self.req("GET", "/assets/%2e%2e/" + name)[0], 404)

    def test_symlink_out_of_assets_is_refused(self):
        name = self.outside_png()
        d = os.path.join(ROOT, "assets", "_t_link_%d" % os.getpid())
        os.makedirs(d)
        self.cleanup.append(d)
        os.symlink(os.path.join(ROOT, name), os.path.join(d, "lien.png"))
        self.assertEqual(self.req("GET", "/assets/%s/lien.png" % os.path.basename(d))[0], 404)


class DemoTest(DemoServer):
    def test_state_lists_demo_sessions(self):
        with open(os.path.join(ROOT, "demo", "terminals.json")) as f:
            want = {t["address"] for t in json.load(f)["terminals"] if t.get("status") and not t.get("parent")}
        got = {a["address"] for a in self.get_json("/api/state")["agents"]}
        self.assertEqual(got, want)

    def test_send_goes_to_out_log(self):
        done = next(a for a in self.get_json("/api/state")["agents"] if a["status"] == "done")
        r = self.post_json("/api/send", {"address": done["address"], "text": "ok", "since_ms": done["since_ms"]})
        self.assertEqual(r, {"ok": True})
        with open(os.path.join(self.demo, "out.log")) as f:
            self.assertIn("send %s ok" % done["address"], f.read())

    def test_classic_is_served_or_404(self):
        code = self.req("GET", "/classic")[0]
        self.assertEqual(code, 200 if os.path.isfile(os.path.join(ROOT, "index-classic.html")) else 404)

    def test_demo_loads_only_new_modules(self):
        log = self.server_log()
        for name in ("stats", "daily", "backup", "oldherdr"):
            self.assertNotIn("module loaded: " + name, log)
