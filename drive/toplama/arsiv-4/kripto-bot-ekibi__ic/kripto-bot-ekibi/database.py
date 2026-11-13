"""SQLite veritabanı: kullanıcılar, izleme listesi, sinyal geçmişi, sohbet hafızası."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from config import ADMIN_IDS, DB_PATH

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _init() -> None:
    with _lock:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id    INTEGER PRIMARY KEY,
                username   TEXT,
                first_name TEXT,
                is_admin   INTEGER DEFAULT 0,
                created_at TEXT,
                last_seen  TEXT
            );
            CREATE TABLE IF NOT EXISTS watchlist (
                chat_id  INTEGER,
                symbol   TEXT,
                added_at TEXT,
                PRIMARY KEY (chat_id, symbol)
            );
            CREATE TABLE IF NOT EXISTS signals (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER,
                symbol     TEXT,
                side       TEXT,
                score      REAL,
                price      REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER,
                role       TEXT,
                content    TEXT,
                model      TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id    INTEGER PRIMARY KEY,
                model      TEXT,
                alarm      INTEGER DEFAULT 1,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sembol      TEXT,
                final_yon   TEXT,
                final_guven INTEGER,
                oydaslik    INTEGER,
                teknik_skor REAL,
                fiyat       REAL,
                hukum       TEXT,
                detay       TEXT,
                alarm       INTEGER DEFAULT 0,
                created_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS botlar (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ad         TEXT UNIQUE,
                emoji      TEXT,
                rol        TEXT,
                model      TEXT,
                aktif      INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS oda_mesaj (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts    TEXT,
                kim   TEXT,
                emoji TEXT,
                kime  TEXT,
                metin TEXT,
                tur   TEXT
            );
            """
        )
        _conn.commit()


_init()


# ---------------------------------------------------------------- kullanıcılar
def upsert_user(chat_id: int, username: str | None, first_name: str | None) -> None:
    admin = 1 if chat_id in ADMIN_IDS else 0
    with _lock:
        _conn.execute(
            """INSERT INTO users (chat_id, username, first_name, is_admin, created_at, last_seen)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   username=excluded.username, first_name=excluded.first_name,
                   is_admin=MAX(users.is_admin, excluded.is_admin),
                   last_seen=excluded.last_seen""",
            (chat_id, username or "", first_name or "", admin, _now(), _now()),
        )
        _conn.commit()


def is_admin(chat_id: int) -> bool:
    with _lock:
        row = _conn.execute("SELECT is_admin FROM users WHERE chat_id=?",
                            (chat_id,)).fetchone()
    return bool(row and row["is_admin"]) or chat_id in ADMIN_IDS


def all_chat_ids() -> list[int]:
    with _lock:
        return [r["chat_id"] for r in _conn.execute("SELECT chat_id FROM users")]


# ---------------------------------------------------------------- izleme listesi
def add_watch(chat_id: int, symbol: str) -> bool:
    """True: yeni eklendi, False: zaten listede."""
    try:
        with _lock:
            _conn.execute(
                "INSERT INTO watchlist (chat_id, symbol, added_at) VALUES (?, ?, ?)",
                (chat_id, symbol.upper(), _now()),
            )
            _conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_watch(chat_id: int, symbol: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM watchlist WHERE chat_id=? AND symbol=?",
                            (chat_id, symbol.upper()))
        _conn.commit()
    return cur.rowcount > 0


def get_watchlist(chat_id: int) -> list[str]:
    with _lock:
        return [r["symbol"] for r in _conn.execute(
            "SELECT symbol FROM watchlist WHERE chat_id=? ORDER BY symbol", (chat_id,))]


def get_watch_targets() -> dict[str, list[int]]:
    """{sembol: [chat_id, ...]} — zamanlanmış tarama için."""
    with _lock:
        rows = _conn.execute("SELECT chat_id, symbol FROM watchlist").fetchall()
    out: dict[str, list[int]] = {}
    for r in rows:
        out.setdefault(r["symbol"], []).append(r["chat_id"])
    return out


# ---------------------------------------------------------------- sinyaller
def save_signal(chat_id: int, symbol: str, side: str, score: float, price: float) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO signals (chat_id, symbol, side, score, price, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, symbol, side, score, price, _now()),
        )
        _conn.commit()


def recent_alert(chat_id: int, symbol: str, side: str, hours: int) -> bool:
    """Aynı sembol+yön için son X saat içinde alarm gönderilmiş mi? (soğuma)"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with _lock:
        row = _conn.execute(
            "SELECT 1 FROM signals WHERE chat_id=? AND symbol=? AND side=? "
            "AND created_at>=? LIMIT 1",
            (chat_id, symbol, side, since),
        ).fetchone()
    return row is not None


def signal_stats() -> dict:
    with _lock:
        n_users = _conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        n_sig = _conn.execute("SELECT COUNT(*) c FROM signals").fetchone()["c"]
        top = _conn.execute(
            "SELECT symbol, COUNT(*) c FROM signals GROUP BY symbol "
            "ORDER BY c DESC LIMIT 5").fetchall()
        longs = _conn.execute(
            "SELECT COUNT(*) c FROM signals WHERE score>=20").fetchone()["c"]
        shorts = _conn.execute(
            "SELECT COUNT(*) c FROM signals WHERE score<=-20").fetchone()["c"]
    return {"kullanici": n_users, "sinyal": n_sig, "top": top,
            "long": longs, "short": shorts}


# ---------------------------------------------------------------- sohbet hafızası
def add_chat_msg(chat_id: int, role: str, content: str, model: str = "") -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, model, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, role, content[:4000], model, _now()),
        )
        _conn.commit()


def get_chat_history(chat_id: int, limit: int = 10) -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT role, content FROM chat_messages WHERE chat_id=? "
            "ORDER BY id DESC LIMIT ?", (chat_id, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_chat(chat_id: int) -> int:
    with _lock:
        cur = _conn.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
        _conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------- ayarlar
def set_model(chat_id: int, model: str) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO chat_settings (chat_id, model, alarm, updated_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   model=excluded.model, updated_at=excluded.updated_at""",
            (chat_id, model, _now()),
        )
        _conn.commit()


def get_model(chat_id: int, default: str) -> str:
    with _lock:
        row = _conn.execute("SELECT model FROM chat_settings WHERE chat_id=?",
                            (chat_id,)).fetchone()
    return row["model"] if row and row["model"] else default


def set_alarm(chat_id: int, on: bool) -> None:
    with _lock:
        _conn.execute(
            """INSERT INTO chat_settings (chat_id, model, alarm, updated_at)
               VALUES (?, '', ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                   alarm=excluded.alarm, updated_at=excluded.updated_at""",
            (chat_id, 1 if on else 0, _now()),
        )
        _conn.commit()


def alarm_enabled(chat_id: int) -> bool:
    with _lock:
        row = _conn.execute("SELECT alarm FROM chat_settings WHERE chat_id=?",
                            (chat_id,)).fetchone()
    return row["alarm"] == 1 if row else True


# ---------------------------------------------------------------- konsensus analizleri
def save_analysis(sembol: str, final_yon: str, final_guven: int, oydaslik: int,
                  teknik_skor: float, fiyat: float, hukum: str,
                  detay_json: str, alarm: int = 0) -> int:
    with _lock:
        cur = _conn.execute(
            """INSERT INTO analyses (sembol, final_yon, final_guven, oydaslik,
                   teknik_skor, fiyat, hukum, detay, alarm, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sembol, final_yon, final_guven, oydaslik, teknik_skor,
             fiyat, hukum, detay_json[:60000], alarm, _now()),
        )
        _conn.commit()
    return cur.lastrowid


def get_analyses(limit: int = 30, only_alarms: bool = False) -> list[dict]:
    q = "SELECT * FROM analyses"
    if only_alarms:
        q += " WHERE alarm=1"
    q += " ORDER BY id DESC LIMIT ?"
    with _lock:
        rows = _conn.execute(q, (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent_analysis_alarm(sembol: str, yon: str, hours: int) -> bool:
    """Soğuma: aynı sembol+yön için son X saatte alarm üretilmiş mi?"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    with _lock:
        row = _conn.execute(
            "SELECT 1 FROM analyses WHERE sembol=? AND final_yon=? AND alarm=1 "
            "AND created_at>=? LIMIT 1", (sembol, yon, since)).fetchone()
    return row is not None


def analysis_stats() -> dict:
    with _lock:
        n = _conn.execute("SELECT COUNT(*) c FROM analyses").fetchone()["c"]
        alarms = _conn.execute(
            "SELECT COUNT(*) c FROM analyses WHERE alarm=1").fetchone()["c"]
        longs = _conn.execute(
            "SELECT COUNT(*) c FROM analyses WHERE final_yon='LONG'").fetchone()["c"]
        shorts = _conn.execute(
            "SELECT COUNT(*) c FROM analyses WHERE final_yon='SHORT'").fetchone()["c"]
    return {"analiz": n, "alarm": alarms, "long": longs, "short": shorts}


# ---------------------------------------------------------------- bot kadrosu
def botlari_yukle(sadece_aktif: bool = False) -> list[dict]:
    q = "SELECT * FROM botlar"
    if sadece_aktif:
        q += " WHERE aktif=1"
    q += " ORDER BY id"
    with _lock:
        rows = _conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def bot_ekle(ad: str, emoji: str, rol: str, model: str) -> int | None:
    """Yeni bot kurar. Ad zaten varsa None döner."""
    try:
        with _lock:
            cur = _conn.execute(
                "INSERT INTO botlar (ad, emoji, rol, model, aktif, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (ad, emoji, rol, model, _now()),
            )
            _conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def bot_guncelle(bot_id: int, **kv) -> bool:
    izinli = {"ad", "emoji", "rol", "model", "aktif"}
    setler, degerler = [], []
    for k, v in kv.items():
        if k in izinli and v is not None:
            setler.append(f"{k}=?")
            degerler.append(v)
    if not setler:
        return False
    degerler.append(bot_id)
    with _lock:
        cur = _conn.execute(
            f"UPDATE botlar SET {', '.join(setler)} WHERE id=?", degerler)
        _conn.commit()
    return cur.rowcount > 0


def bot_sil(bot_id: int) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM botlar WHERE id=?", (bot_id,))
        _conn.commit()
    return cur.rowcount > 0


def bot_bul(ad: str) -> dict | None:
    with _lock:
        row = _conn.execute(
            "SELECT * FROM botlar WHERE LOWER(ad)=LOWER(?)", (ad,)).fetchone()
    return dict(row) if row else None


def bot_sayisi() -> int:
    with _lock:
        return _conn.execute("SELECT COUNT(*) c FROM botlar").fetchone()["c"]


# ---------------------------------------------------------------- bot odası
def oda_ekle(kim: str, metin: str, tur: str = "bot",
             emoji: str = "", kime: str = "") -> int:
    with _lock:
        cur = _conn.execute(
            "INSERT INTO oda_mesaj (ts, kim, emoji, kime, metin, tur) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), kim, emoji, kime, metin[:4000], tur),
        )
        _conn.commit()
    return cur.lastrowid


def oda_gecmis(limit: int = 120, son_id: int = 0) -> list[dict]:
    """son_id > 0 ise yalnız ondan yeni mesajlar (canlı akış için)."""
    if son_id > 0:
        with _lock:
            rows = _conn.execute(
                "SELECT * FROM oda_mesaj WHERE id>? ORDER BY id LIMIT ?",
                (son_id, limit)).fetchall()
    else:
        with _lock:
            rows = _conn.execute(
                "SELECT * FROM (SELECT * FROM oda_mesaj ORDER BY id DESC LIMIT ?) "
                "ORDER BY id", (limit,)).fetchall()
    return [dict(r) for r in rows]


def oda_son_id() -> int:
    with _lock:
        row = _conn.execute(
            "SELECT id FROM oda_mesaj ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else 0


def oda_temizle() -> int:
    with _lock:
        cur = _conn.execute("DELETE FROM oda_mesaj")
        _conn.commit()
    return cur.rowcount
