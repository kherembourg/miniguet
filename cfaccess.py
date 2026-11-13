"""Cloudflare Tunnel + Access support. Stdlib only.

When the board is published through a Cloudflare Tunnel, every request reaches the server from cloudflared on
127.0.0.1, so "loopback = the Mac itself" no longer holds. Such requests are recognised (public host name, or
the Cf-* headers the edge adds) and must carry a valid Cloudflare Access token (Cf-Access-Jwt-Assertion), checked
here: RS256 signature against the team's public keys, audience (the Access application's AUD tag), issuer,
expiry, and optionally the e-mail address. Access already blocks unauthenticated visitors at the edge; this check
is a second lock, in case the Access application is ever removed or misconfigured.

Configuration: ~/.local/state/herdr-board/cloudflare.json
    {"host": "miniguet.example.com",          # public name served by the tunnel
     "team": "myteam",                        # <team>.cloudflareaccess.com
     "aud": "<Application Audience (AUD) tag>",
     "emails": ["me@example.com"]}            # optional: only these identities (case-insensitive)
"""
import base64, hashlib, json, os, threading, time, urllib.request

STATE_DIR = os.path.expanduser("~/.local/state/herdr-board")
CONF_FILE = os.path.join(STATE_DIR, "cloudflare.json")
CERTS_TTL = 3600
SKEW = 60                                          # seconds of clock skew tolerated on exp / nbf
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")   # DER prefix of a SHA-256 DigestInfo


def load_conf():
    try:
        with open(CONF_FILE) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    if not (c.get("host") and c.get("team") and c.get("aud")):
        print("cloudflare.json: host, team and aud are required; tunnel access disabled", flush=True)
        return None
    c["host"] = c["host"].lower()
    c["emails"] = [e.lower() for e in c.get("emails") or []]
    return c


CONF = load_conf()


def configured():
    return CONF is not None


def public_host():
    return CONF["host"] if CONF else None


def via_tunnel(headers):
    """True if the request came through Cloudflare (it then must be authenticated, whatever its source address)."""
    host = (headers.get("Host") or "").rsplit(":", 1)[0].lower()
    if CONF and host == CONF["host"]:
        return True
    return any(headers.get(k) for k in ("Cf-Connecting-Ip", "Cf-Ray", "Cf-Access-Jwt-Assertion"))


def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


_certs = {"at": 0, "keys": {}}
_lock = threading.Lock()


def _keys(force=False):
    with _lock:
        if force or time.time() - _certs["at"] > CERTS_TTL or not _certs["keys"]:
            url = f"https://{CONF['team']}.cloudflareaccess.com/cdn-cgi/access/certs"
            with urllib.request.urlopen(url, timeout=10) as r:
                jwks = json.load(r)
            keys = {}
            for k in jwks.get("keys", []):
                if k.get("kty") == "RSA":
                    keys[k["kid"]] = (int.from_bytes(_b64(k["n"]), "big"), int.from_bytes(_b64(k["e"]), "big"))
            _certs.update(at=time.time(), keys=keys)
        return _certs["keys"]


def _rs256_ok(signing_input, sig, n, e):
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    t = _DIGEST_INFO + hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return em == expected


def identity(headers):
    """The verified e-mail of the Access user, or None if the request carries no valid token."""
    if not CONF:
        return None
    tok = headers.get("Cf-Access-Jwt-Assertion") or ""
    try:
        h64, p64, s64 = tok.split(".")
        head, claims, sig = json.loads(_b64(h64)), json.loads(_b64(p64)), _b64(s64)
        if head.get("alg") != "RS256":
            return None
        keys = _keys()
        if head.get("kid") not in keys:
            keys = _keys(force=True)               # key rotation
        if head.get("kid") not in keys or not _rs256_ok(f"{h64}.{p64}".encode(), sig, *keys[head["kid"]]):
            return None
        now = time.time()
        aud = claims.get("aud")
        aud = aud if isinstance(aud, list) else [aud]
        if CONF["aud"] not in aud:
            return None
        if claims.get("iss") != f"https://{CONF['team']}.cloudflareaccess.com":
            return None
        if not (claims.get("exp", 0) + SKEW > now >= claims.get("nbf", 0) - SKEW):
            return None
        email = (claims.get("email") or "").lower()
        if CONF["emails"] and email not in CONF["emails"]:
            return None
        return email or claims.get("sub") or "?"
    except Exception as e:
        print("cloudflare access: token rejected:", type(e).__name__, flush=True)
        return None
