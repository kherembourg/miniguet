"""Local speech to text (Whisper) for the board: GET /api/voice, POST /api/transcribe. Pure core, wired by register(srv)."""
import base64, json, os, signal, subprocess, threading, time, uuid

MAX_BYTES = 5 * 1024 * 1024
MAX_SECONDS = 60
DEFAULTS = {"bin": "/opt/homebrew/bin/whisper-cli", "ffmpeg": "/opt/homebrew/bin/ffmpeg",
            "model": "~/.local/share/miniguet/whisper/ggml-large-v3-turbo-q5_0.bin"}
BUSY = threading.Lock()   # one transcoding at a time


class VoiceError(Exception):
    pass


def conf(state_dir):
    """Binaries and model: DEFAULTS overridden by <state_dir>/whisper.json."""
    c = dict(DEFAULTS)
    try:
        with open(os.path.join(state_dir, "whisper.json")) as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return {k: os.path.expanduser(v) for k, v in c.items()}


def available(c):
    return all(os.path.isfile(c[k]) for k in ("bin", "ffmpeg", "model"))


def _run(cmd, deadline, name):
    """stdout of `cmd`, killed (with its children) when the shared deadline passes."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise VoiceError(f"délai de {MAX_SECONDS} s dépassé")
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        raise VoiceError(f"{name} introuvable ou inutilisable : {e}")
    try:
        out, err = p.communicate(timeout=left)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise VoiceError(f"délai de {MAX_SECONDS} s dépassé")
    if p.returncode:
        raise VoiceError(f"{name} a échoué : {(err or out).strip()[-200:]}")
    return out


def transcribe(audio, c, scratch, timeout=MAX_SECONDS):
    """Text said in `audio` (any format ffmpeg reads). Refuses over MAX_BYTES, a second concurrent call, and past `timeout` in all."""
    if len(audio) > MAX_BYTES:
        raise VoiceError(f"audio trop gros ({MAX_BYTES // (1024 * 1024)} Mo au plus)")
    if not BUSY.acquire(blocking=False):
        raise VoiceError("une transcription est déjà en cours")
    try:
        deadline = time.monotonic() + timeout
        base = os.path.join(scratch, uuid.uuid4().hex)
        src, wav = base + ".in", base + ".wav"
        try:
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            _run([c["ffmpeg"], "-y", "-i", src, "-t", str(MAX_SECONDS), "-ar", "16000", "-ac", "1", wav], deadline, "ffmpeg")
            out = _run([c["bin"], "-m", c["model"], "-l", "fr", "-nt", "-np", "-f", wav], deadline, "whisper")
        finally:
            for p in (src, wav):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return " ".join(ln.strip() for ln in out.splitlines() if ln.strip())
    finally:
        BUSY.release()


def register(srv):
    def reply(obj):
        return 200, "application/json", json.dumps(obj, ensure_ascii=False).encode()

    def voice_route(h, body):
        return reply({"available": available(conf(srv.STATE_DIR))})

    def transcribe_route(h, body):
        if not srv.paired(h):
            return reply({"error": "appareil non appairé : ouvre l'adresse d'appairage (scripts/pair-url.sh sur le Mac) sur cet appareil"})
        b64 = str(json.loads(body).get("audio", ""))
        if len(b64) > -(-MAX_BYTES // 3) * 4:
            return reply({"error": f"audio trop gros ({MAX_BYTES // (1024 * 1024)} Mo au plus)"})
        try:
            audio = base64.b64decode(b64, validate=True)
            return reply({"text": transcribe(audio, conf(srv.STATE_DIR), srv.SCRATCH)})
        except (VoiceError, ValueError) as e:
            return reply({"error": str(e) if isinstance(e, VoiceError) else "audio illisible"})

    srv.ROUTES["GET"]["/api/voice"] = voice_route
    srv.ROUTES["POST"]["/api/transcribe"] = transcribe_route
