"""Process-local, bounded Synthetic session sandboxes; never uses V2_DATA_DIR."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import atexit
import shutil
import tempfile
import threading
import time
import uuid

from v2.service import Store
from v2.alerts import AlertEngine

SEED = Path(__file__).with_name('demo_data') / 'phase2_synthetic.xlsx'


class DemoUnavailable(Exception):
    """Safe message boundary; internal paths/errors must not reach the public UI."""


@dataclass
class Session:
    path: Path
    touched: float
    created: float
    active: int = 0
    store: object = None
    lock: object = field(default_factory=threading.RLock)


class DemoSessions:
    def __init__(self, *, parent=None, seed=SEED, ttl=1800, lifetime=7200,
                 capacity=64, max_bytes=8 * 1024 * 1024, clock=time.monotonic, sweep=60):
        self.root = Path(tempfile.mkdtemp(prefix='v21-public-', dir=parent)).resolve()
        self.seed = Path(seed)
        self.ttl, self.lifetime, self.capacity, self.max_bytes = ttl, lifetime, capacity, max_bytes
        self.clock = clock
        self.entries = {}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.worker = None
        if sweep:
            self.worker = threading.Thread(target=self._sweep, args=(sweep,), daemon=True)
            self.worker.start()
        atexit.register(self.close)

    def _sweep(self, interval):
        while not self.stop.wait(interval):
            self.cleanup()

    def _remove(self, token):
        entry = self.entries[token]
        # Only paths generated and registered by this instance may be deleted.
        if entry.path.parent != self.root or entry.path.name != token or entry.active:
            return False
        try:
            shutil.rmtree(entry.path)
        except FileNotFoundError:
            pass
        except OSError:
            return False  # Retry next sweep; never discard accounting on failure.
        del self.entries[token]
        return True

    def cleanup(self):
        with self.lock:
            now = self.clock()
            for token, entry in list(self.entries.items()):
                if not entry.active and (now-entry.touched >= self.ttl or now-entry.created >= self.lifetime):
                    self._remove(token)

    def discard(self, token):
        with self.lock:
            if token in self.entries:
                self._remove(token)

    @contextmanager
    def lease(self, token=None):
        with self.lock:
            self.cleanup()
            if self.stop.is_set():
                raise DemoUnavailable('演示服务正在重启，请稍后重试。')
            entry = self.entries.get(token)
            if entry is None:
                if len(self.entries) >= self.capacity:
                    raise DemoUnavailable('演示会话已满，请稍后重试。')
                token = uuid.uuid4().hex
                path = self.root / token
                path.mkdir(mode=0o700)
                now = self.clock()
                entry = self.entries[token] = Session(path, now, now)
            entry.active += 1
        try:
            with entry.lock:
                if entry.store is None:
                    try:
                        content = self.seed.read_bytes()
                        store = Store(entry.path)
                        result = store.ingest('Synthetic.xlsx', content, 'workbook', 'demo', '模拟初始化')
                        if result['status'] != 'imported':
                            raise ValueError('seed import failed')
                        AlertEngine(store).run('demo', as_of=date(2026, 10, 21), actor='模拟初始化')
                        entry.store = store
                    except Exception as exc:
                        raise DemoUnavailable('模拟数据初始化失败，请重置演示或稍后重试。') from exc
                if sum(p.stat().st_size for p in entry.path.rglob('*') if p.is_file()) > self.max_bytes:
                    raise DemoUnavailable('本会话已达到临时数据限额，请重置演示。')
                yield token, entry.store
        finally:
            with self.lock:
                entry.active -= 1
                entry.touched = self.clock()
                if entry.store is None and not entry.active:
                    self._remove(token)

    def close(self):
        self.stop.set()
        with self.lock:
            for token in list(self.entries):
                self._remove(token)
            if not self.entries:
                try:
                    self.root.rmdir()
                except OSError:
                    pass
        atexit.unregister(self.close)


_manager = None
_manager_lock = threading.Lock()


def sessions():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DemoSessions()
        return _manager
