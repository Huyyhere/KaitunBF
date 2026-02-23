import discord
from discord import app_commands
import aiohttp
import asyncio
import json
import time
import sqlite3
import os
import uuid
import logging
import requests
from getpass import getpass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("afk")

def _clear():
    os.system("cls" if os.name == "nt" else "clear")

BOT_TOKEN = getpass("Nhập token bot Discord: ").strip()
_clear()

BASE_URL            = "https://altare.sh"
MAX_ACC             = 50
RETRY_DELAY         = 30
MAX_HB_FAIL         = 5
CMD_COOLDOWN        = 15
GLOBAL_LOG_INTERVAL = 60
WEBHOOK_RATE_LIMIT  = 1.2
GLOBAL_LOG_WEBHOOK  = "https://discord.com/api/webhooks/1475494025506197580/oTJbBsz4jbKC_ERoZkrC6yHhVirItTYnH3UmUOnMmDuvNKvcB3zMLBxiJnO7QzvU3CEP"

DATA_DIR   = "data"
CONFIG_DIR = os.path.join(DATA_DIR, "configs")
DB_PATH    = os.path.join(DATA_DIR, "afk.db")
os.makedirs(CONFIG_DIR, exist_ok=True)

intents = discord.Intents.default()
client  = discord.Client(intents=intents)
tree    = app_commands.CommandTree(client)

runtime: dict[str, "Account"] = {}
executor = ThreadPoolExecutor(max_workers=32)
_cooldowns: dict[int, float] = defaultdict(float)


def check_cooldown(uid: int) -> float:
    rem = CMD_COOLDOWN - (time.monotonic() - _cooldowns[uid])
    return round(rem, 1) if rem > 0 else 0.0

def set_cooldown(uid: int):
    _cooldowns[uid] = time.monotonic()

def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S  %d/%m/%Y")

def parse_token(raw: str) -> str:
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return f"Bearer {raw}"


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    with db_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                acc_id    TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                file_path TEXT NOT NULL,
                added_by  INTEGER NOT NULL,
                added_at  TEXT NOT NULL
            )
        """)

def db_insert(acc_id: str, name: str, file_path: str, added_by: int):
    with db_conn() as c:
        c.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            (acc_id, name, file_path, added_by,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

def db_delete(acc_id: str):
    with db_conn() as c:
        c.execute("DELETE FROM accounts WHERE acc_id=?", (acc_id,))

def db_count() -> int:
    with db_conn() as c:
        return c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

def db_all():
    with db_conn() as c:
        return c.execute("SELECT * FROM accounts ORDER BY added_at").fetchall()

def db_get(acc_id: str):
    with db_conn() as c:
        return c.execute(
            "SELECT * FROM accounts WHERE acc_id=?", (acc_id,)
        ).fetchone()


_webhook_last: dict[str, float] = {}

async def send_webhook(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    message_id: str | None = None
) -> str | None:
    key  = url.split("/messages/")[0]
    wait = WEBHOOK_RATE_LIMIT - (time.monotonic() - _webhook_last.get(key, 0))
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        if message_id is None:
            async with session.post(
                url + "?wait=true", json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                _webhook_last[key] = time.monotonic()
                if r.status in (200, 204):
                    return (await r.json()).get("id")
        else:
            async with session.patch(
                f"{url}/messages/{message_id}", json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                _webhook_last[key] = time.monotonic()
                if r.status in (200, 204):
                    return message_id
    except Exception as e:
        log.warning(f"Webhook lỗi: {e}")
    return None


class Account:
    def __init__(self, acc_id: str, name: str, cfg: dict, added_by: int):
        self.acc_id             = acc_id
        self.name               = name
        self.cfg                = cfg
        self.added_by           = added_by
        self.token              = parse_token(cfg.get("token", ""))
        self.tenant_id          = cfg.get("tenant_id", "").strip()
        self.webhook            = cfg.get("discord_webhook", "").strip()
        self.heartbeat_interval = int(cfg.get("heartbeat_interval", 30))
        self.stats_interval     = int(cfg.get("stats_interval", 60))
        self.notify_interval    = int(cfg.get("notify_interval_seconds", 10))

        self.running        = False
        self.session_start: datetime | None = None
        self.credits_start  = 0.0
        self.balance        = 0.0
        self.hb_ok          = 0
        self.hb_fail        = 0
        self.message_id: str | None = None
        self.notify_count   = 0
        self.restart_count  = 0
        self.status         = "đang khởi động"
        self._pm            = 0.35
        self._tasks: list[asyncio.Task] = []

    def _h(self) -> dict:
        h = {
            "Authorization": self.token,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Origin":        BASE_URL,
            "Referer":       f"{BASE_URL}/billing/rewards/afk",
            "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if self.tenant_id:
            h["altare-selected-tenant-id"] = self.tenant_id
        return h

    def _get(self, url: str) -> dict | list | None:
        try:
            r = requests.get(url, headers=self._h(), timeout=15)
            if r.ok:
                return r.json()
            log.warning(f"[{self.name}] GET {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.warning(f"[{self.name}] GET lỗi: {e}")
        return None

    def _post(self, url: str) -> tuple[bool, int, str]:
        try:
            r = requests.post(url, headers=self._h(), json={}, timeout=15)
            if not r.ok:
                log.warning(f"[{self.name}] POST {url.split('/')[-1]} → {r.status_code}: {r.text[:200]}")
            return r.ok, r.status_code, r.text
        except Exception as e:
            log.warning(f"[{self.name}] POST lỗi: {e}")
            return False, 0, str(e)

    def _detect_tenant(self) -> str | None:
        data = self._get(f"{BASE_URL}/api/tenants")
        if not data:
            return None
        items = data.get("items", data) if isinstance(data, dict) else data
        if not items:
            log.warning(f"[{self.name}] Danh sách tenant rỗng")
            return None
        tid = items[0].get("id") or items[0].get("tenantId")
        log.info(f"[{self.name}] Tenant: {tid}")
        return tid

    def _fetch_balance(self) -> float | None:
        data = self._get(f"{BASE_URL}/api/tenants")
        if not data:
            return None
        items = data.get("items", data) if isinstance(data, dict) else data
        for item in (items if isinstance(items, list) else []):
            if item.get("id") == self.tenant_id:
                c = item.get("creditsCents")
                return round(c / 100, 4) if c is not None else None
        if isinstance(items, list) and items:
            c = items[0].get("creditsCents")
            return round(c / 100, 4) if c is not None else None
        return None

    def _fetch_pm(self) -> float:
        data = self._get(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards")
        if data:
            afk = data.get("afk") if isinstance(data.get("afk"), dict) else {}
            return float(afk.get("perMinute") or data.get("perMinute") or 0.35)
        return 0.35

    def _heartbeat(self) -> bool:
        ok, _, _ = self._post(
            f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/heartbeat"
        )
        return ok

    def _start_api(self) -> tuple[bool, str]:
        ok, code, body = self._post(
            f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/start"
        )
        return (True, "OK") if ok else (False, f"HTTP {code}: {body[:150]}")

    def _stop_api(self):
        self._post(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/stop")

    async def _run(self, fn, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, fn, *args)

    def elapsed(self) -> str:
        return str(datetime.now() - self.session_start).split(".")[0] if self.session_start else "?"

    def hb_rate(self) -> int:
        return round(self.hb_ok / max(self.hb_ok + self.hb_fail, 1) * 100)

    def earned(self) -> float:
        return round(self.balance - self.credits_start, 4) if self.credits_start else 0.0

    def icon(self) -> str:
        if self.status == "hoạt động":  return "🟢"
        if "khởi động" in self.status:  return "🔄"
        return "🔴"

    def _reset(self):
        self.hb_ok         = 0
        self.hb_fail       = 0
        self.session_start = datetime.now()
        self.credits_start = 0.0
        self.message_id    = None
        self.status        = "đang khởi động"

    async def _loop_hb(self):
        fails = 0
        while self.running:
            ok = await self._run(self._heartbeat)
            if ok:
                self.hb_ok += 1
                fails = 0
            else:
                self.hb_fail += 1
                fails += 1
                log.warning(f"[{self.name}] HB thất bại {fails}/{MAX_HB_FAIL}")
                if fails >= MAX_HB_FAIL:
                    fails = 0
                    if not await self._restart():
                        break
            await asyncio.sleep(self.heartbeat_interval)

    async def _loop_stats(self):
        while self.running:
            bal = await self._run(self._fetch_balance)
            if bal is not None:
                if not self.credits_start:
                    self.credits_start = bal
                self.balance = bal
                log.info(
                    f"[{self.name}] {bal:.4f} cr  "
                    f"+{self.earned():.4f}  "
                    f"{self.elapsed()}  "
                    f"hb {self.hb_rate()}%  "
                    f"restart×{self.restart_count}"
                )
            await asyncio.sleep(self.stats_interval)

    async def _loop_notify(self, session: aiohttp.ClientSession):
        await asyncio.sleep(3)
        while self.running:
            await self._push(session)
            await asyncio.sleep(self.notify_interval)

    async def _loop_sse(self, session: aiohttp.ClientSession):
        raw  = self.token.replace("Bearer ", "").strip()
        url  = f"https://api.altare.sh/subscribe?token={raw}"
        hdrs = {
            "Accept":        "text/event-stream",
            "Cache-Control": "no-cache",
            "Authorization": self.token,
            "Origin":        BASE_URL,
            "User-Agent":    "Mozilla/5.0",
        }
        while self.running:
            try:
                async with session.get(
                    url, headers=hdrs,
                    timeout=aiohttp.ClientTimeout(total=None, connect=15)
                ) as r:
                    if r.status == 200:
                        async for _ in r.content:
                            if not self.running:
                                return
                    else:
                        await asyncio.sleep(15)
            except Exception:
                if self.running:
                    await asyncio.sleep(15)
            if self.running:
                await asyncio.sleep(5)

    async def _push(self, session: aiohttp.ClientSession):
        if not self.webhook:
            return
        self.notify_count += 1
        payload = {
            "username":   "Altare AFK",
            "avatar_url": "https://altare.sh/favicon.ico",
            "embeds": [{
                "author": {
                    "name":     self.name,
                    "icon_url": "https://altare.sh/favicon.ico"
                },
                "color": 0x2ecc71 if self.status == "hoạt động" else 0xe67e22,
                "fields": [
                    {
                        "name":   "📡  Trạng thái",
                        "value":  f"{self.icon()} **{self.status.capitalize()}**\n> Khởi động lại: `{self.restart_count} lần`",
                        "inline": False
                    },
                    {
                        "name":   "💰  Số dư",
                        "value":  f"```fix\n{self.balance:.4f} cr\n```",
                        "inline": True
                    },
                    {
                        "name":   "📈  Kiếm được",
                        "value":  f"```diff\n+ {self.earned():.4f} cr\n```",
                        "inline": True
                    },
                    {
                        "name":   "⚡  Tốc độ",
                        "value":  f"```fix\n{self._pm} cr/phút\n```",
                        "inline": True
                    },
                    {
                        "name":   "⏱️  Uptime",
                        "value":  f"```fix\n{self.elapsed()}\n```",
                        "inline": True
                    },
                    {
                        "name":   "💓  Heartbeat",
                        "value":  f"```fix\n✓{self.hb_ok}  ✗{self.hb_fail}  ({self.hb_rate()}%)\n```",
                        "inline": True
                    },
                ],
                "footer": {
                    "text": f"#{self.notify_count}  •  {now_str()}"
                },
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }]
        }
        self.message_id = await send_webhook(session, self.webhook, payload, self.message_id)

    async def _restart(self) -> bool:
        self.status = "đang khởi động lại"
        await self._run(self._stop_api)
        await asyncio.sleep(RETRY_DELAY)
        for i in range(1, 6):
            log.info(f"[{self.name}] Thử lại lần {i}/5...")
            self._reset()
            if not self.tenant_id:
                self.tenant_id = await self._run(self._detect_tenant)
            if self.tenant_id:
                ok, msg = await self._run(self._start_api)
                if ok:
                    self.restart_count += 1
                    self.status = "hoạt động"
                    log.info(f"[{self.name}] Khởi động lại thành công lần {self.restart_count}")
                    return True
                log.warning(f"[{self.name}] API start lỗi: {msg}")
            await asyncio.sleep(RETRY_DELAY)
        self.status  = "lỗi — không thể khởi động lại"
        self.running = False
        log.error(f"[{self.name}] Dừng hẳn sau 5 lần thất bại")
        return False

    async def start(self) -> tuple[bool, str]:
        if not self.tenant_id:
            self.tenant_id = await self._run(self._detect_tenant)
        if not self.tenant_id:
            return False, (
                "Không tìm được Tenant ID.\n\n"
                "**Cách lấy token đúng:**\n"
                "1. Mở altare.sh → đăng nhập\n"
                "2. F12 → tab **Network** → Refresh trang\n"
                "3. Click bất kỳ request nào → **Headers**\n"
                "4. Copy giá trị **Authorization** (`Bearer eyJ...`)"
            )
        ok, msg = await self._run(self._start_api)
        if not ok:
            return False, f"API start thất bại: {msg}"

        self.running       = True
        self.session_start = datetime.now()
        self.status        = "hoạt động"

        pm = await self._run(self._fetch_pm)
        self._pm = pm

        session = aiohttp.ClientSession()
        loop    = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._loop_sse(session)),
            loop.create_task(self._loop_hb()),
            loop.create_task(self._loop_stats()),
            loop.create_task(self._loop_notify(session)),
        ]
        log.info(f"[{self.name}] Đã bắt đầu (id={self.acc_id[:8]})")
        return True, "OK"

    async def stop(self):
        self.running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        await self._run(self._stop_api)
        log.info(f"[{self.name}] Đã dừng")


_global_msg_id: str | None = None

async def _global_log_loop():
    await client.wait_until_ready()
    async with aiohttp.ClientSession() as s:
        while not client.is_closed():
            await asyncio.sleep(GLOBAL_LOG_INTERVAL)
            try:
                await _push_global(s)
            except Exception as e:
                log.warning(f"Global log lỗi: {e}")

async def _push_global(session: aiohttp.ClientSession):
    global _global_msg_id
    accs = list(runtime.values())
    if not accs:
        return

    total_bal  = sum(a.balance for a in accs)
    total_earn = sum(a.earned() for a in accs)
    total_hbok = sum(a.hb_ok for a in accs)
    total_hbfl = sum(a.hb_fail for a in accs)
    total_rate = round(total_hbok / max(total_hbok + total_hbfl, 1) * 100)
    total_pm   = round(sum(a._pm for a in accs), 4)
    active     = sum(1 for a in accs if a.status == "hoạt động")
    error      = sum(1 for a in accs if "lỗi" in a.status)

    rows = []
    for i, a in enumerate(accs, 1):
        row = db_get(a.acc_id)
        adder = f"<@{row['added_by']}>" if row else "?"
        rows.append(
            f"{a.icon()} **{i}. {a.name}**\n"
            f"┣ 💰 `{a.balance:.4f} cr`  📈 `+{a.earned():.4f} cr`  ⚡ `{a._pm} cr/phút`\n"
            f"┣ ⏱️ `{a.elapsed()}`  💓 `{a.hb_rate()}%`  🔄 `{a.restart_count}×`\n"
            f"┗ 👤 {adder}"
        )

    payload = {
        "username":   "Altare Hệ Thống",
        "avatar_url": "https://altare.sh/favicon.ico",
        "embeds": [{
            "title": "🖥️  TỔNG QUAN HỆ THỐNG  —  ALTARE AFK",
            "color": 0x00d4aa,
            "fields": [
                {
                    "name":   "━━━━━━  📊 CHỈ SỐ TỔNG  ━━━━━━",
                    "value":  "\u200b",
                    "inline": False
                },
                {
                    "name":   "💰  Tổng số dư",
                    "value":  f"```fix\n{total_bal:.4f} cr\n```",
                    "inline": True
                },
                {
                    "name":   "📈  Tổng kiếm được",
                    "value":  f"```diff\n+ {total_earn:.4f} cr\n```",
                    "inline": True
                },
                {
                    "name":   "⚡  Tốc độ tổng",
                    "value":  f"```fix\n{total_pm} cr/phút\n```",
                    "inline": True
                },
                {
                    "name":   "🖥️  Tổng tài khoản",
                    "value":  f"```fix\n{len(accs)} / {MAX_ACC}\n```",
                    "inline": True
                },
                {
                    "name":   "🟢  Đang hoạt động",
                    "value":  f"```fix\n{active} tài khoản\n```",
                    "inline": True
                },
                {
                    "name":   "🔴  Đang lỗi",
                    "value":  f"```fix\n{error} tài khoản\n```",
                    "inline": True
                },
                {
                    "name":   "💓  Heartbeat tổng",
                    "value":  f"```fix\n✓{total_hbok}  ✗{total_hbfl}  ({total_rate}% OK)\n```",
                    "inline": False
                },
                {
                    "name":   "━━━━━━  📋 DANH SÁCH TÀI KHOẢN  ━━━━━━",
                    "value":  "\n\n".join(rows)[:4000] if rows else "*(trống)*",
                    "inline": False
                },
            ],
            "footer": {
                "text":     f"🔄 Cập nhật mỗi {GLOBAL_LOG_INTERVAL}s  •  {now_str()}",
                "icon_url": "https://altare.sh/favicon.ico"
            },
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }]
    }
    result = await send_webhook(session, GLOBAL_LOG_WEBHOOK, payload, _global_msg_id)
    if result:
        _global_msg_id = result


async def _autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=f"{a.icon()} {a.name}", value=a.acc_id)
        for a in runtime.values()
        if current.lower() in a.name.lower()
    ][:25]

def _cooldown_embed() -> discord.Embed:
    return discord.Embed(
        title="⏳  Chờ một chút!",
        description=f"Vui lòng chờ trước khi dùng lệnh tiếp theo.",
        color=0xf39c12
    )

def _cooldown_embed_with(rem: float) -> discord.Embed:
    e = discord.Embed(
        title="⏳  Chờ một chút!",
        description=f"Vui lòng chờ **{rem}s** trước khi dùng lệnh tiếp theo.",
        color=0xf39c12
    )
    return e


@client.event
async def on_ready():
    db_init()
    rows   = db_all()
    loaded = 0
    print(f"\n{'═'*52}")
    print(f"  Bot      : {client.user}")
    print(f"  Dữ liệu  : {DATA_DIR}/")
    print(f"  Config   : {CONFIG_DIR}/")
    print(f"  Database : {DB_PATH}")
    print(f"  Cooldown : {CMD_COOLDOWN}s")
    print(f"  Khôi phục: {len(rows)} tài khoản")
    print(f"{'═'*52}")
    for row in rows:
        fpath = row["file_path"]
        if not os.path.exists(fpath):
            print(f"  ✗  {row['name']}  —  file không tồn tại")
            continue
        with open(fpath, encoding="utf-8") as f:
            cfg = json.load(f)
        acc = Account(row["acc_id"], row["name"], cfg, row["added_by"])
        ok, msg = await acc.start()
        if ok:
            runtime[acc.acc_id] = acc
            loaded += 1
            print(f"  ✓  {row['name']}  ({row['acc_id'][:8]})")
        else:
            print(f"  ✗  {row['name']}  —  {msg[:80]}")
    print(f"{'═'*52}")
    print(f"  Thành công: {loaded}/{len(rows)}")
    print(f"{'═'*52}\n")
    await tree.sync()
    asyncio.get_event_loop().create_task(_global_log_loop())
    async with aiohttp.ClientSession() as s:
        await _push_global(s)


@tree.command(name="thêm", description="Thêm tài khoản AFK mới vào hệ thống")
async def cmd_them(interaction: discord.Interaction, file: discord.Attachment):
    uid = interaction.user.id
    rem = check_cooldown(uid)
    if rem:
        await interaction.response.send_message(embed=_cooldown_embed_with(rem), ephemeral=True)
        return
    set_cooldown(uid)

    if db_count() >= MAX_ACC:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌  Hết slot",
                description=f"Hệ thống đã đạt tối đa **{MAX_ACC} tài khoản**.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    if not file.filename.endswith(".json"):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌  Sai định dạng",
                description="Chỉ chấp nhận file **`.json`**.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        cfg = json.loads(await file.read())
    except Exception:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌  File không hợp lệ",
                description="Không đọc được file JSON. Kiểm tra lại định dạng.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    token = cfg.get("token", "").strip()
    if not token:
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌  Thiếu token",
                description="File JSON phải có trường **`token`**.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    raw_jwt = token.replace("Bearer ", "").replace("bearer ", "").strip()
    if not raw_jwt.startswith("eyJ"):
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️  Token có thể không đúng",
                description=(
                    "Token không có dạng JWT (`eyJ...`).\n\n"
                    "**Cách lấy token đúng:**\n"
                    "1. Mở altare.sh → đăng nhập\n"
                    "2. `F12` → tab **Network** → Refresh trang\n"
                    "3. Click bất kỳ request nào → **Headers**\n"
                    "4. Copy giá trị **Authorization** (`Bearer eyJ...`)\n\n"
                    "Bot vẫn thử khởi động nhưng có thể thất bại."
                ),
                color=0xf39c12
            ), ephemeral=True
        )

    name   = cfg.get("name", "").strip() or file.filename.removesuffix(".json")
    acc_id = str(uuid.uuid4())
    fpath  = os.path.join(CONFIG_DIR, f"{acc_id}.json")

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    acc = Account(acc_id, name, cfg, uid)
    ok, msg = await acc.start()

    if not ok:
        os.remove(fpath)
        await interaction.followup.send(
            embed=discord.Embed(
                title="❌  Khởi động thất bại",
                description=msg,
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    runtime[acc_id] = acc
    db_insert(acc_id, name, fpath, uid)

    embed = discord.Embed(title="✅  Đã thêm tài khoản AFK", color=0x2ecc71)
    embed.add_field(
        name="📋  Thông tin",
        value=(
            f"**Tên:** {name}\n"
            f"**Tenant:** `{acc.tenant_id[:24]}...`\n"
            f"**ID:** `{acc_id[:12]}...`"
        ),
        inline=True
    )
    embed.add_field(
        name="⚙️  Cấu hình",
        value=(
            f"**Heartbeat:** `{acc.heartbeat_interval}s`\n"
            f"**Cập nhật:** `{acc.stats_interval}s`\n"
            f"**Thông báo:** `{acc.notify_interval}s`"
        ),
        inline=True
    )
    embed.add_field(
        name="🖥️  Hệ thống",
        value=f"**Slot còn:** `{MAX_ACC - db_count()}/{MAX_ACC}`",
        inline=True
    )
    embed.set_footer(text=f"Thêm bởi {interaction.user}  •  {now_str()}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    async with aiohttp.ClientSession() as s:
        await _push_global(s)


@tree.command(name="xóa", description="Dừng và xoá một tài khoản AFK")
@app_commands.describe(tài_khoản="Chọn tài khoản muốn xoá")
@app_commands.autocomplete(tài_khoản=_autocomplete)
async def cmd_xoa(interaction: discord.Interaction, tài_khoản: str):
    uid = interaction.user.id
    rem = check_cooldown(uid)
    if rem:
        await interaction.response.send_message(embed=_cooldown_embed_with(rem), ephemeral=True)
        return
    set_cooldown(uid)

    acc = runtime.get(tài_khoản)
    if not acc:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌  Không tìm thấy",
                description="Tài khoản không tồn tại. Dùng `/danh-sách` để xem.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    row  = db_get(tài_khoản)
    name = acc.name
    await acc.stop()
    del runtime[tài_khoản]
    db_delete(tài_khoản)

    if row and os.path.exists(row["file_path"]):
        os.remove(row["file_path"])

    embed = discord.Embed(title="🗑️  Đã xoá tài khoản", color=0xe74c3c)
    embed.add_field(
        name="📋  Kết quả",
        value=(
            f"**Tên:** {name}\n"
            "**Trạng thái:** Đã dừng\n"
            "**File config:** Đã xoá\n"
            "**Database:** Đã cập nhật"
        ),
        inline=False
    )
    embed.set_footer(text=f"Xoá bởi {interaction.user}  •  {now_str()}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    async with aiohttp.ClientSession() as s:
        await _push_global(s)


@tree.command(name="danh-sách", description="Xem toàn bộ tài khoản AFK trong hệ thống")
async def cmd_danh_sach(interaction: discord.Interaction):
    uid = interaction.user.id
    rem = check_cooldown(uid)
    if rem:
        await interaction.response.send_message(embed=_cooldown_embed_with(rem), ephemeral=True)
        return
    set_cooldown(uid)

    if not runtime:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📋  Danh sách tài khoản",
                description="Chưa có tài khoản nào.\nDùng `/thêm` để bắt đầu.",
                color=0x95a5a6
            ), ephemeral=True
        )
        return

    accs          = list(runtime.values())
    total_bal     = sum(a.balance for a in accs)
    total_earn    = sum(a.earned() for a in accs)
    active        = sum(1 for a in accs if a.status == "hoạt động")

    embed = discord.Embed(
        title=f"📋  Danh sách tài khoản AFK  —  {len(accs)}/{MAX_ACC}",
        color=0x00d4aa
    )
    embed.add_field(
        name="📊  Tóm tắt",
        value=(
            f"🟢 Đang chạy: **{active}**   "
            f"💰 Tổng số dư: **{total_bal:.4f} cr**   "
            f"📈 Tổng kiếm: **+{total_earn:.4f} cr**"
        ),
        inline=False
    )
    for i, acc in enumerate(accs, 1):
        embed.add_field(
            name=f"{acc.icon()}  {i}. {acc.name}",
            value=(
                f"💰 `{acc.balance:.4f} cr`  📈 `+{acc.earned():.4f}`\n"
                f"⏱️ `{acc.elapsed()}`  💓 `{acc.hb_rate()}%`  🔄 `{acc.restart_count}×`\n"
                f"👤 <@{acc.added_by}>"
            ),
            inline=True
        )
    embed.set_footer(text=f"Dùng /trạng-thái để xem chi tiết  •  {now_str()}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="trạng-thái", description="Xem chi tiết một tài khoản AFK")
@app_commands.describe(tài_khoản="Chọn tài khoản muốn xem")
@app_commands.autocomplete(tài_khoản=_autocomplete)
async def cmd_trang_thai(interaction: discord.Interaction, tài_khoản: str):
    uid = interaction.user.id
    rem = check_cooldown(uid)
    if rem:
        await interaction.response.send_message(embed=_cooldown_embed_with(rem), ephemeral=True)
        return
    set_cooldown(uid)

    acc = runtime.get(tài_khoản)
    if not acc:
        await interaction.response.send_message(
            embed=discord.Embed(
                title="❌  Không tìm thấy",
                description="Tài khoản không tồn tại. Dùng `/danh-sách` để xem.",
                color=0xe74c3c
            ), ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    pm  = await acc._run(acc._fetch_pm)
    acc._pm = pm
    row = db_get(tài_khoản)

    embed = discord.Embed(
        title=f"{acc.icon()}  Chi tiết  —  {acc.name}",
        color=0x2ecc71 if acc.status == "hoạt động" else 0xe67e22
    )
    embed.add_field(
        name="📡  Vận hành",
        value=(
            f"**Trạng thái:** {acc.icon()} {acc.status.capitalize()}\n"
            f"**Khởi động lại:** `{acc.restart_count} lần`\n"
            f"**Uptime:** `{acc.elapsed()}`"
        ),
        inline=True
    )
    embed.add_field(
        name="💰  Tài chính",
        value=(
            f"**Số dư:** `{acc.balance:.4f} cr`\n"
            f"**Kiếm được:** `+{acc.earned():.4f} cr`\n"
            f"**Tốc độ:** `{pm} cr/phút`"
        ),
        inline=True
    )
    embed.add_field(
        name="💓  Heartbeat",
        value=(
            f"**Tỉ lệ OK:** `{acc.hb_rate()}%`\n"
            f"**Thành công:** `{acc.hb_ok}`\n"
            f"**Thất bại:** `{acc.hb_fail}`"
        ),
        inline=True
    )
    embed.add_field(
        name="🔑  Tenant ID",
        value=f"`{acc.tenant_id}`",
        inline=False
    )
    embed.add_field(
        name="👤  Thêm bởi",
        value=f"<@{acc.added_by}>",
        inline=True
    )
    if row:
        embed.add_field(
            name="🕐  Thêm lúc",
            value=f"`{row['added_at']}`",
            inline=True
        )
        embed.add_field(
            name="📁  File",
            value=f"`{os.path.basename(row['file_path'])[:24]}...`",
            inline=True
        )
    embed.set_footer(text=f"Cập nhật lúc {now_str()}")
    await interaction.followup.send(embed=embed, ephemeral=True)


client.run(BOT_TOKEN)
