"""Fake `srv` (the server module) and handler for the module tests: no hc, no Claude, no server.py import."""
import os, shutil, tempfile, threading, weakref


class FakeHandler:
    def __init__(self, path, paired=True, body=""):
        self.path = path
        self.paired = paired
        self.body = body


class FakeSrv:
    def __init__(self, screen=None, screen_error=None, terms=None, pids=None, msgs=None, keys_error=None):
        self.ROUTES = {"GET": {}, "POST": {}}
        self.SNAPSHOT_HOOKS = []
        self.AGENT_SOURCES = []
        self.screens = [list(screen or [])] if screen is None or screen and isinstance(screen[0], str) else [list(s) for s in screen]
        self.screen_error = screen_error
        self.reads = 0                     # number of read_screen calls
        self.terms = terms or []
        self.pids = pids or {}             # address -> pid
        self.msgs = msgs or {}             # pid -> [(ts_ms, role, text)]
        self.keys_error = keys_error
        self.keys_sent = []                # [(address, key)]
        self.LOCK = threading.Lock()
        self.SEND_LOCK = threading.Lock()
        self.STATE_DIR = tempfile.mkdtemp(prefix="miniguet-fake-")
        weakref.finalize(self, shutil.rmtree, self.STATE_DIR, True)
        self.SCRATCH = os.path.join(self.STATE_DIR, "scratch")
        os.makedirs(self.SCRATCH, mode=0o700)
        self.SENTF = os.path.join(self.STATE_DIR, "sent.jsonl")

    def pid_of(self, addr):
        return self.pids.get(addr)

    def messages(self, pid):
        return self.msgs.get(pid, [])

    def read_screen(self, addr):
        self.reads += 1
        if self.screen_error:
            raise self.screen_error
        # a list of screens is read in turn (the last one stays): the screen can change between two reads
        return self.screens[min(self.reads - 1, len(self.screens) - 1)]

    def snapshot(self):
        return self.terms

    def main_agent(self, t):
        return not t.get("parent") and t.get("state") == "live" and bool(t.get("status"))

    def paired(self, h):
        return h.paired

    def hc_keys(self, addr, key):
        self.keys_sent.append((addr, key))
        return self.keys_error
