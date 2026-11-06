#!/usr/bin/env python3
"""Encrypted backup of Miniguet's state (~/.local/state/herdr-board) to Cloudflare D1, plus a local mirror.

Why encrypted: on a shared Cloudflare account any administrator can read any D1 database. Everything is encrypted on this
Mac before it leaves, with a key that lives in the macOS Keychain: D1 only ever holds ciphertext, hashed file keys, sizes and
dates. Without the key nothing can be read; without the key nothing can be restored either (keep the recovery key somewhere safe).

Format of one stored file: b"MG1" + nonce(16) + openssl(AES-256-CBC, key = HMAC(master, "enc"+nonce)) + HMAC-SHA256 tag.
The plaintext is a JSON header line {"path", "mtime"} + newline + the file bytes. Encrypt-then-MAC: the tag is checked first.
The file key in the database is HMAC(master, "path"+path): names are not visible either.

Tables (SQLite, identical on D1 and in the local mirror): files(id, pkey, sha, size, chunks, ts), chunks(file_id, n, data), meta.
Every changed file is a new row (history is kept); an unchanged file is not uploaded again.

Commands:   python3 backup.py status | run | verify | list | restore --to DIR [--at ISO_DATE] | setup --account ID | export-key | import-key
Server:     register(srv) runs a backup 2 minutes after start, then every 6 hours; GET /api/backup/status.
Tests:      HERDR_BOARD_BACKUP_KEY_HEX overrides the Keychain key; HERDR_BOARD_STATE overrides the state folder.
"""
import base64, getpass, hashlib, hmac, json, os, re, secrets, sqlite3, subprocess, sys, threading, time, urllib.request

STATE = os.environ.get("HERDR_BOARD_STATE") or os.path.expanduser("~/.local/state/herdr-board")
CONF = f"{STATE}/backup_config.json"          # {"d1": {"account_id": ..., "database_id": ...}}  (the API token is in the Keychain)
MIRROR = f"{STATE}/backups/mirror.sqlite"     # local encrypted copy (history of every change), always on
KC_KEY, KC_TOKEN = "miniguet-backup-key", "miniguet-d1-token"
EXCLUDE = re.compile(r"^(pair_token|access\.log|gcal\.json|backup_config\.json|scratch/|backups/|.*\.tmp$)")
MAX_FILE = 20 * 1024 * 1024
CHUNK = 48 * 1024                             # bytes of ciphertext per row (base64 ~64 KB, under D1's 100 KB statement limit)
EVERY_S = 6 * 3600
OPENSSL = next((p for p in ("/opt/homebrew/bin/openssl", "/usr/local/bin/openssl", "/usr/bin/openssl") if os.path.exists(p)), "openssl")

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT, pkey TEXT NOT NULL, sha TEXT NOT NULL, size INTEGER, chunks INTEGER, ts INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS files_pkey ON files(pkey, id)",
    "CREATE TABLE IF NOT EXISTS chunks(file_id INTEGER NOT NULL, n INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(file_id, n))",
    "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)",
]
STATUS = {"last": None, "running": False}


# ---------------------------------------------------------------- keys
def _keychain(service, value=None):
    acct = os.environ.get("USER", "miniguet")
    if value is None:
        r = subprocess.run(["/usr/bin/security", "find-generic-password", "-a", acct, "-s", service, "-w"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    # the secret goes through the stdin of `security -i`, never through argv (visible to every process in `ps`)
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value) or not re.fullmatch(r"[A-Za-z0-9._ -]+", acct + service):
        raise ValueError("unexpected characters in a Keychain value")
    r = subprocess.run(["/usr/bin/security", "-i"], input=f'add-generic-password -U -a "{acct}" -s "{service}" -w "{value}"\n',
                       capture_output=True, text=True)
    if r.returncode or "error" in (r.stdout + r.stderr).lower():
        raise RuntimeError("Keychain: " + (r.stderr or r.stdout).strip()[:200])


def master_key(create=False):
    h = os.environ.get("HERDR_BOARD_BACKUP_KEY_HEX") or _keychain(KC_KEY)
    if not h and create:
        h = secrets.token_hex(32)
        _keychain(KC_KEY, h)
    if not h:
        raise RuntimeError("no backup key: run `python3 backup.py setup` first")
    k = bytes.fromhex(h)
    if len(k) != 32:
        raise RuntimeError("the backup key must be 32 bytes (64 hex characters)")
    return k


def _h(key, *parts):
    return hmac.new(key, b"".join(parts), hashlib.sha256).digest()


# ---------------------------------------------------------------- crypto (openssl for AES, hmac/hashlib for the rest)
def _openssl(mode, data, pw):
    r_fd, w_fd = os.pipe()
    os.write(w_fd, pw.encode() + b"\n")
    os.close(w_fd)
    try:
        p = subprocess.run([OPENSSL, "enc", mode, "-aes-256-cbc", "-pbkdf2", "-iter", "1", "-md", "sha256", "-pass", f"fd:{r_fd}"],
                           input=data, capture_output=True, pass_fds=(r_fd,))
    finally:
        os.close(r_fd)
    if p.returncode:
        raise RuntimeError("openssl: " + p.stderr.decode()[:200])
    return p.stdout


def encrypt(key, plain):
    nonce = secrets.token_bytes(16)
    ct = _openssl("-e", plain, _h(key, b"enc", nonce).hex())
    body = b"MG1" + nonce + ct
    return body + _h(key, b"mac", body)


def decrypt(key, blob):
    if blob[:3] != b"MG1" or len(blob) < 3 + 16 + 32:
        raise ValueError("not a Miniguet backup blob")
    body, tag = blob[:-32], blob[-32:]
    if not hmac.compare_digest(tag, _h(key, b"mac", body)):
        raise ValueError("wrong key or corrupted data (authentication failed)")
    return _openssl("-d", body[19:], _h(key, b"enc", body[3:19]).hex())


def pkey(key, path):
    return _h(key, b"path", path.encode()).hex()[:32]


# ---------------------------------------------------------------- backends: query(sql, params) -> list of dict rows
class Local:
    name = "local"

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        os.chmod(path, 0o600)
        self.lock = threading.Lock()

    def query(self, sql, params=()):
        with self.lock:
            cur = self.db.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()] if cur.description else []
            self.db.commit()
            return rows, cur.lastrowid


class D1:
    name = "d1"

    def __init__(self, account, database, token):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
        self.token = token

    def query(self, sql, params=()):
        req = urllib.request.Request(self.url, json.dumps({"sql": sql, "params": list(params)}).encode(),
                                     {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    j = json.load(r)
                break
            except Exception as e:
                if attempt == 3:
                    raise RuntimeError(f"D1: {str(e)[:150]}")
                time.sleep(2 ** attempt)
        if not j.get("success"):
            raise RuntimeError("D1: " + json.dumps(j.get("errors"))[:200])
        res = j["result"][0]
        return res.get("results", []), (res.get("meta") or {}).get("last_row_id")


def backends():
    out = [Local(MIRROR)]
    try:
        with open(CONF) as f:
            d1 = json.load(f).get("d1")
        tok = os.environ.get("HERDR_BOARD_D1_TOKEN") or _keychain(KC_TOKEN)
        if d1 and tok:
            out.append(D1(d1["account_id"], d1["database_id"], tok))
    except (OSError, ValueError, KeyError):
        pass
    for b in out:
        for s in SCHEMA:
            b.query(s)
    return out


# ---------------------------------------------------------------- backup / restore
def _files():
    for root, dirs, names in os.walk(STATE):
        rel_root = os.path.relpath(root, STATE)
        for n in names:
            rel = n if rel_root == "." else os.path.join(rel_root, n)
            if EXCLUDE.match(rel) or os.path.islink(os.path.join(root, n)):
                continue
            try:
                st = os.stat(os.path.join(root, n))
            except OSError:
                continue
            if st.st_size <= MAX_FILE:
                yield rel, st


def push(b, key, rel, data, mtime):
    k = pkey(key, rel)
    sha = hashlib.sha256(data).hexdigest()
    rows, _ = b.query("SELECT sha FROM files WHERE pkey=? ORDER BY id DESC LIMIT 1", [k])
    if rows and rows[0]["sha"] == sha:
        return False
    blob = encrypt(key, json.dumps({"path": rel, "mtime": mtime}).encode() + b"\n" + data)
    parts = [blob[i:i + CHUNK] for i in range(0, len(blob), CHUNK)] or [b""]
    _, fid = b.query("INSERT INTO files(pkey, sha, size, chunks, ts) VALUES(?,?,?,?,?)", [k, sha, len(data), len(parts), int(time.time() * 1000)])
    for n, p in enumerate(parts):
        b.query("INSERT INTO chunks(file_id, n, data) VALUES(?,?,?)", [fid, n, base64.b64encode(p).decode()])
    return True


def run(only=None):
    """Back up every changed file to every backend. Returns {backend: {"uploaded": n, "unchanged": n, "error": str|None}}."""
    key = master_key(create=False)
    snap = {}
    for rel, st in _files():
        try:
            with open(os.path.join(STATE, rel), "rb") as f:
                snap[rel] = (f.read(), int(st.st_mtime))
        except OSError:
            pass
    report = {}
    for b in backends():
        if only and b.name != only:
            continue
        r = report[b.name] = {"uploaded": 0, "unchanged": 0, "error": None}
        for rel, (data, mt) in sorted(snap.items()):
            try:
                r["uploaded" if push(b, key, rel, data, mt) else "unchanged"] += 1
            except Exception as e:
                r["error"] = f"{rel}: {str(e)[:150]}"
                break
        b.query("INSERT OR REPLACE INTO meta(k, v) VALUES('last_run', ?)", [str(int(time.time() * 1000))])
    STATUS["last"] = {"at": int(time.time() * 1000), "report": report}
    return report


def fetch(b, key, file_id, chunks):
    rows, _ = b.query("SELECT n, data FROM chunks WHERE file_id=? ORDER BY n", [file_id])
    if len(rows) != chunks:
        raise ValueError(f"file {file_id}: {len(rows)} chunks instead of {chunks}")
    plain = decrypt(key, b"".join(base64.b64decode(r["data"]) for r in rows))
    head, _, data = plain.partition(b"\n")
    return json.loads(head), data


def latest(b, at_ms=None):
    """Newest version (<= at_ms) of every file key: [{"id", "pkey", "sha", "size", "chunks", "ts"}]."""
    sql = "SELECT f.id, f.pkey, f.sha, f.size, f.chunks, f.ts FROM files f JOIN (SELECT pkey, MAX(id) m FROM files {w} GROUP BY pkey) x ON f.id = x.m"
    rows, _ = b.query(sql.format(w="WHERE ts <= ?" if at_ms else ""), [at_ms] if at_ms else [])
    return rows


def verify(only=None):
    """Download, decrypt and compare the newest version of every backed-up file with the file on disk."""
    key = master_key()
    out = {}
    for b in backends():
        if only and b.name != only:
            continue
        r = out[b.name] = {"ok": 0, "differs": [], "missing_locally": [], "errors": []}
        for row in latest(b, None):
            try:
                head, data = fetch(b, key, row["id"], row["chunks"])
                p = os.path.join(STATE, head["path"])
                if not os.path.exists(p):
                    r["missing_locally"].append(head["path"])
                elif hashlib.sha256(open(p, "rb").read()).hexdigest() == hashlib.sha256(data).hexdigest():
                    r["ok"] += 1
                else:
                    r["differs"].append(head["path"])   # changed since the last backup: normal for live files
            except Exception as e:
                r["errors"].append(f"{row['id']}: {str(e)[:120]}")
    return out


def restore(dest, at_ms=None, backend="local"):
    key = master_key()
    b = next(x for x in backends() if x.name == backend)
    os.makedirs(dest, exist_ok=True)
    n = 0
    for row in latest(b, at_ms):
        head, data = fetch(b, key, row["id"], row["chunks"])
        rel = os.path.normpath(head["path"])
        if rel.startswith("..") or os.path.isabs(rel):
            raise ValueError("unsafe path in backup: " + rel)
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        os.utime(p, (head["mtime"], head["mtime"]))
        n += 1
    return n


# ---------------------------------------------------------------- Cloudflare setup (needs an API token with D1 Edit)
def _cf(method, url, token, body=None):
    req = urllib.request.Request("https://api.cloudflare.com/client/v4" + url, json.dumps(body).encode() if body is not None else None,
                                 {"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def setup(account, token, name="miniguet"):
    dbs = _cf("GET", f"/accounts/{account}/d1/database?name={name}", token)
    found = [d for d in dbs.get("result", []) if d.get("name") == name]
    db = found[0] if found else _cf("POST", f"/accounts/{account}/d1/database", token, {"name": name})["result"]
    _keychain(KC_TOKEN, token)
    os.makedirs(STATE, exist_ok=True)
    with open(CONF, "w") as f:
        json.dump({"d1": {"account_id": account, "database_id": db["uuid"], "name": name}}, f)
    os.chmod(CONF, 0o600)
    master_key(create=True)
    return db["uuid"]


# ---------------------------------------------------------------- server integration
def register(srv):
    def loop():
        time.sleep(120)
        while True:
            try:
                STATUS["running"] = True
                run()
            except Exception as e:
                STATUS["last"] = {"at": int(time.time() * 1000), "error": str(e)[:200]}
                print("backup failed:", e, flush=True)
            finally:
                STATUS["running"] = False
            time.sleep(EVERY_S)

    def status(h, body):
        try:
            d1 = bool(json.load(open(CONF)).get("d1"))
        except (OSError, ValueError):
            d1 = False
        return 200, "application/json", json.dumps({**STATUS, "d1_configured": d1, "key": bool(_keychain(KC_KEY))}).encode()

    srv.ROUTES["GET"]["/api/backup/status"] = status
    if os.environ.get("HERDR_BOARD_BACKUP_KEY_HEX") or _keychain(KC_KEY):   # no key yet: nothing runs until `setup`/`init`
        threading.Thread(target=loop, daemon=True).start()


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "init":    # key only (local mirror works without Cloudflare)
        k = master_key(create=True)
        print("Key stored in the Keychain. Recovery key (keep it in your password manager, it is shown only here):", k.hex())
    elif cmd == "export-key":
        print(master_key().hex())
    elif cmd == "import-key":
        _keychain(KC_KEY, getpass.getpass("Recovery key (64 hex characters): ").strip())
        print("stored")
    elif cmd == "setup":
        acct = argv[argv.index("--account") + 1]
        tok = os.environ.get("HERDR_BOARD_D1_TOKEN") or getpass.getpass("Cloudflare API token (D1 Edit): ").strip()
        print("D1 database ready:", setup(acct, tok))
        print("Recovery key (keep it in your password manager):", master_key().hex())
    elif cmd == "run":
        print(json.dumps(run(), indent=1))
    elif cmd == "verify":
        print(json.dumps(verify(), indent=1))
    elif cmd == "list":
        for b in backends():
            print(b.name, [(r["size"], time.strftime("%F %T", time.localtime(r["ts"] / 1000))) for r in latest(b)])
    elif cmd == "restore":
        dest = argv[argv.index("--to") + 1]
        at = None
        if "--at" in argv:
            at = int(time.mktime(time.strptime(argv[argv.index("--at") + 1], "%Y-%m-%d")) * 1000) + 86399000
        be = argv[argv.index("--from") + 1] if "--from" in argv else "local"
        print(restore(dest, at, be), "files restored to", dest)
    else:
        try:
            d1 = json.load(open(CONF)).get("d1")
        except (OSError, ValueError):
            d1 = None
        print(json.dumps({"key_in_keychain": bool(_keychain(KC_KEY)), "d1": bool(d1), "mirror": os.path.exists(MIRROR), "last": STATUS["last"]}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
