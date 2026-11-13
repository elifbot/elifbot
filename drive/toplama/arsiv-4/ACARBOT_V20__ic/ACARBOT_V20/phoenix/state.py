import json, os, tempfile
from threading import RLock

class StateStore:
    """Atomic JSON state with process-local single-writer protection."""
    def __init__(self, path):
        self.path = path
        self._lock = RLock()

    def load(self):
        with self._lock:
            try:
                with open(self.path, encoding='utf8') as f:
                    return json.load(f)
            except FileNotFoundError:
                return {'positions': {}, 'orders': {}, 'equity': None, 'risk': {}}
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"state file is corrupt: {self.path}") from exc

    def save(self, state):
        with self._lock:
            d = os.path.dirname(os.path.abspath(self.path)) or '.'
            fd, tmp = tempfile.mkstemp(prefix='.phoenix-', dir=d, text=True)
            try:
                with os.fdopen(fd, 'w', encoding='utf8') as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
