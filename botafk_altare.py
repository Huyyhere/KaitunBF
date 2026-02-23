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
from getpass import getpass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("afk_bot")

def _clear():
    os.system("cls" if os.name == "nt" else "clear")

BOT_TOKEN = getpass("Nhập token bot Discord: ").strip()
_clear()
log.info("Token đã nhận. Đang khởi động bot...")

BASE_URL            = "https://altare.sh"
MAX_ACC             = 50
RETRY_DELAY         = 30
MAX_HB_FAIL         = 5
GLOBAL_LOG_WEBHOOK  = "https://discord.com/api/webhooks/1475494025506197580/oTJbBsz4jbKC_ERoZkrC6yHhVirItTYnH3UmUOnMmDuvNKvcB3zMLBxiJnO7QzvU3CEP"
GLOBAL_LOG_INTERVAL = 60
WEBHOOK_RATE_LIMIT  = 1.2
CMD_COOLDOWN        = 15
CONFIGS_DIR         = "configs"

os.makedirs(CONFIGS_DIR, exist_ok=True)

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


def db():
    conn = sqlite3.connect("afk.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                acc_id    TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                file_path TEXT NOT NULL,
                added_by  INTEGER NOT NULL,
                added_at  TEXT NOT NULL
            )
        """)

def db_insert(acc_id: str, name: str, file_path: str, added_by: int):
    with db() as conn:
        conn.execute(
            "INSERT INTO accounts VALUES (?, ?, ?, ?, ?)",
            (acc_id, name, file_path, added_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )

def db_delete(acc_id: str):
    with db() as conn:
        conn.execute("DELETE FROM accounts WHERE acc_id=?", (acc_id,))

def db_count() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

def db_all():
    with db() as conn:
        return conn.execute("SELECT * FROM accounts ORDER BY added_at").fetchall()

def db_get(acc_id: str):
    with db() as conn:
        return conn.execute("SELECT * FROM accounts WHERE acc_id=?", (acc_id,)).fetchone()


_webhook_last_sent: dict[str, float] = {}

async def send_webhook(
    session: aiohttp.ClientSession,
    url: str,
    payload: dict,
    message_id: str | None = None
) -> str | None:
    key  = url.split("/messages/")[0]
    wait = WEBHOOK_RATE_LIMIT - (time.monotonic() - _webhook_last_sent.get(key, 0))
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        if message_id is None:
            async with session.post(url + "?wait=true", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                _webhook_last_sent[key] = time.monotonic()
                if r.status in (200, 204):
                    return (await r.json()).get("id")
        else:
            async with session.patch(f"{url}/messages/{message_id}", json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                _webhook_last_sent[key] = time.monotonic()
                if r.status in (200, 204):
                    return message_id
    except Exception as e:
        log.warning(f"Webhook error: {e}")
    return None


class Account:
    def __init__(self, acc_id: str, name: str, cfg: dict, added_by: int):
        self.acc_id             = acc_id
        self.name               = name
        self.cfg                = cfg
        self.added_by           = added_by
        self.token              = cfg["token"] if cfg["token"].startswith("Bearer ") else f"Bearer {cfg['token']}"
        self.tenant_id          = cfg.get("tenant_id", "").strip()
        self.webhook            = cfg.get("discord_webhook", "").strip()
        self.heartbeat_interval = cfg.get("heartbeat_interval", 30)
        self.stats_interval     = cfg.get("stats_interval", 60)
        self.notify_interval    = cfg.get("notify_interval_seconds", 10)

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
        self._per_min_cache = 0.35
        self._tasks: list[asyncio.Task] = []

    def _headers(self) -> dict:
        h = {
            "Authorization": self.token,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Origin":        BASE_URL,
            "Referer":       f"{BASE_URL}/billing/rewards/afk",
            "User-Agent":    "Mozilla/5.0",
        }
        if self.tenant_id:
            h["altare-selected-tenant-id"] = self.tenant_id
        return h

    def _sync_get_json(self, url: str) -> dict | list | None:
        import requests
        try:
            r = requests.get(url, headers=self._headers(), timeout=10)
            return r.json() if r.ok else None
        except:
            return None

    def _sync_post(self, url: str) -> bool:
        import requests
        try:
            r = requests.post(url, headers=self._headers(), json={}, timeout=10)
            return r.status_code in (200, 201, 204)
        except:
            return False

    def _sync_detect_tenant(self) -> str | None:
        data = self._sync_get_json(f"{BASE_URL}/api/tenants")
        if not data:
            return None
        items = data.get("items", data) if isinstance(data, dict) else data
        if items:
            return items[0].get("id") or items[0].get("tenantId")
        return None

    def _sync_fetch_balance(self) -> float | None:
        data = self._sync_get_json(f"{BASE_URL}/api/tenants")
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

    def _sync_fetch_per_minute(self) -> float:
        data = self._sync_get_json(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards")
        if data:
            afk = data.get("afk") if isinstance(data.get("afk"), dict) else {}
            return afk.get("perMinute") or data.get("perMinute") or 0.35
        return 0.35

    def _sync_heartbeat(self) -> bool:
        return self._sync_post(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/heartbeat")

    def _sync_api_start(self) -> bool:
        return self._sync_post(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/start")

    def _sync_api_stop(self):
        import requests
        try:
            requests.post(
                f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/stop",
                headers=self._headers(), json={}, timeout=10
            )
        except:
            pass

    async def detect_tenant(self) -> str | None:
        return await asyncio.get_event_loop().run_in_executor(executor, self._sync_detect_tenant)

    async def fetch_balance(self) -> float | None:
        return await asyncio.get_event_loop().run_in_executor(executor, self._sync_fetch_balance)

    async def fetch_per_minute(self) -> float:
        pm = await asyncio.get_event_loop().run_in_executor(executor, self._sync_fetch_per_minute)
        self._per_min_cache = pm
        return pm

    async def do_heartbeat(self) -> bool:
        return await asyncio.get_event_loop().run_in_executor(executor, self._sync_heartbeat)

    async def api_start(self) -> bool:
        return await asyncio.get_event_loop().run_in_executor(executor, self._sync_api_start)

    async def api_stop(self):
        await asyncio.get_event_loop().run_in_executor(executor, self._sync_api_stop)

    def elapsed_str(self) -> str:
        return str(datetime.now() - self.session_start).split(".")[0] if self.session_start else "?"

    def hb_rate(self) -> int:
        return round(self.hb_ok / max(self.hb_ok + self.hb_fail, 1) * 100)

    def earned(self) -> float:
        return round(self.balance - self.credits_start, 4) if self.credits_start else 0.0

    def _reset_state(self):
        self.hb_ok         = 0
        self.hb_fail       = 0
        self.session_start = datetime.now()
        self.credits_start = 0.0
        self.message_id    = None
        self.status        = "đang khởi động"

    async def push_discord(self, session: aiohttp.ClientSession):
        if not self.webhook:
            return
        self.notify_count += 1
        status_bar = "🟢 Hoạt động" if self.status == "hoạt động" else f"🔄 {self.status}"
        payload = {
            "username":   "Altare AFK",
            "avatar_url": "https://altare.sh/favicon.ico",
            "embeds": [{
                "author": {"name": f"Altare AFK  •  {self.name}"},
                "color": 0x2ecc71 if self.status == "hoạt động" else 0xe67e22,
                "fields": [
                    {"name": "Trạng thái", "value": f"`{status_bar}`  •  Restart: `{self.restart_count}×`", "inline": False},
                    {"name": "Số dư",      "value": f"```\n{self.balance:>12.4f} cr\n```",                  "inline": True},
                    {"name": "Kiếm được",  "value": f"```diff\n+ {self.earned():.4f} cr\n```",              "inline": True},
                    {"name": "Tốc độ",     "value": f"```\n{self._per_min_cache} cr/min\n```",              "inline": True},
                    {"name": "Uptime",     "value": f"```\n{self.elapsed_str()}\n```",                      "inline": True},
                    {"name": "Heartbeat",  "value": f"```\nOK {self.hb_ok}  Fail {self.hb_fail}  ({self.hb_rate()}%)\n```", "inline": True},
                ],
                "footer":    {"text": f"#{self.notify_count}  •  {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}"},
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }]
        }
        self.message_id = await send_webhook(session, self.webhook, payload, self.message_id)

    async def _loop_heartbeat(self):
        consecutive_fail = 0
        while self.running:
            ok = await self.do_heartbeat()
            if ok:
                self.hb_ok += 1
                consecutive_fail = 0
            else:
                self.hb_fail += 1
                consecutive_fail += 1
                log.warning(f"[{self.name}] heartbeat fail ({consecutive_fail}/{MAX_HB_FAIL})")
                if consecutive_fail >= MAX_HB_FAIL:
                    consecutive_fail = 0
                    if not await self._do_restart():
                        break
            await asyncio.sleep(self.heartbeat_interval)

    async def _loop_stats(self):
        while self.running:
            bal = await self.fetch_balance()
            if bal is not None:
                if not self.credits_start:
                    self.credits_start = bal
                self.balance = bal
                log.info(f"[{self.name}] {bal:.4f} cr  +{self.earned():.4f}  {self.elapsed_str()}  hb {self.hb_rate()}%  restart×{self.restart_count}")
            await asyncio.sleep(self.stats_interval)

    async def _loop_notify(self, session: aiohttp.ClientSession):
        await asyncio.sleep(3)
        while self.running:
            await self.push_discord(session)
            await asyncio.sleep(self.notify_interval)

    async def _loop_sse(self, session: aiohttp.ClientSession):
        raw  = self.token.replace("Bearer ", "")
        url  = f"https://api.altare.sh/subscribe?token={raw}"
        hdrs = {"Accept": "text/event-stream", "Cache-Control": "no-cache",
                "Authorization": self.token, "Origin": BASE_URL, "User-Agent": "Mozilla/5.0"}
        while self.running:
            try:
                async with session.get(url, headers=hdrs, timeout=aiohttp.ClientTimeout(total=None, connect=15)) as r:
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

    async def _do_restart(self) -> bool:
        self.status = "đang khởi động lại"
        await self.api_stop()
        await asyncio.sleep(RETRY_DELAY)
        for attempt in range(1, 6):
            log.info(f"[{self.name}] thử lần {attempt}/5...")
            self._reset_state()
            if not self.tenant_id:
                self.tenant_id = await self.detect_tenant()
            if self.tenant_id and await self.api_start():
                self.restart_count += 1
                self.status = "hoạt động"
                log.info(f"[{self.name}] restart thành công (lần {self.restart_count})")
                return True
            await asyncio.sleep(RETRY_DELAY)
        self.status  = "lỗi — không thể restart"
        self.running = False
        log.error(f"[{self.name}] thất bại sau 5 lần, dừng hẳn")
        return False

    async def start(self) -> tuple[bool, str]:
        if not self.tenant_id:
            self.tenant_id = await self.detect_tenant()
        if not self.tenant_id:
            return False, "Không tìm được tenant ID — kiểm tra lại token."
        if not await self.api_start():
            return False, "Gọi API start AFK thất bại."
        self.running       = True
        self.session_start = datetime.now()
        self.status        = "hoạt động"
        session = aiohttp.ClientSession()
        loop    = asyncio.get_event_loop()
        self._tasks = [
            loop.create_task(self._loop_sse(session)),
            loop.create_task(self._loop_heartbeat()),
            loop.create_task(self._loop_stats()),
            loop.create_task(self._loop_notify(session)),
        ]
        log.info(f"[{self.name}] đã bắt đầu  (id={self.acc_id[:8]})")
        return True, "OK"

    async def stop(self):
        self.running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        await self.api_stop()
        log.info(f"[{self.name}] đã dừng")


_global_log_message_id: str | None = None

async def global_log_loop():
    await client.wait_until_ready()
    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            await asyncio.sleep(GLOBAL_LOG_INTERVAL)
            try:
                await push_global_log(session)
            except Exception as e:
                log.warning(f"Global log error: {e}")

async def push_global_log(session: aiohttp.ClientSession):
    global _global_log_message_id
    all_accs = list(runtime.values())
    if not all_accs:
        return
    total_balance = sum(a.balance for a in all_accs)
    total_earned  = sum(a.earned() for a in all_accs)
    active_count  = sum(1 for a in all_accs if a.status == "hoạt động")

    lines = []
    for a in all_accs:
        icon = "🟢" if a.status == "hoạt động" else "🔄" if "khởi động" in a.status else "🔴"
        row  = db_get(a.acc_id)
        adder = f"<@{row['added_by']}>" if row else "?"
        lines.append(
            f"{icon} `{a.name:<18}` "
            f"bal `{a.balance:>10.4f}` "
            f"earn `+{a.earned():>8.4f}` "
            f"hb `{a.hb_rate():>3}%` "
            f"up `{a.elapsed_str()}`  "
            f"by {adder}"
        )

    payload = {
        "username":   "Altare Global Monitor",
        "avatar_url": "https://altare.sh/favicon.ico",
        "embeds": [{
            "title":       "📊  Tổng quan toàn hệ thống  —  Altare AFK",
            "color":       0x00d4aa,
            "description": "\n".join(lines),
            "fields": [
                {"name": "Tổng acc",       "value": f"`{len(all_accs)}/{MAX_ACC}`",        "inline": True},
                {"name": "Hoạt động",      "value": f"`{active_count}/{len(all_accs)}`",   "inline": True},
                {"name": "Tổng số dư",     "value": f"`{total_balance:.4f} cr`",            "inline": True},
                {"name": "Tổng kiếm được", "value": f"```diff\n+ {total_earned:.4f} cr\n```", "inline": True},
            ],
            "footer":    {"text": f"Cập nhật mỗi {GLOBAL_LOG_INTERVAL}s  •  {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}"},
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }]
    }
    result = await send_webhook(session, GLOBAL_LOG_WEBHOOK, payload, _global_log_message_id)
    if result:
        _global_log_message_id = result


async def autocomplete_acc(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=f"{a.name}  [{a.acc_id[:6]}]", value=a.acc_id)
        for a in runtime.values()
        if current.lower() in a.name.lower() or current.lower() in a.acc_id
    ][:25]


@client.event
async def on_ready():
    db_init()
    rows   = db_all()
    loaded = 0
    print(f"\n{'─'*55}")
    print(f"  Bot      : {client.user}")
    print(f"  Configs  : ./{CONFIGS_DIR}/")
    print(f"  Database : afk.db")
    print(f"  Cooldown : {CMD_COOLDOWN}s/lệnh")
    print(f"  Khôi phục: {len(rows)} tài khoản...")
    print(f"{'─'*55}")
    for row in rows:
        fpath = row["file_path"]
        if not os.path.exists(fpath):
            print(f"  ✗  {row['name']}  —  file không tồn tại: {fpath}")
            continue
        with open(fpath, encoding="utf-8") as f:
            cfg = json.load(f)
        acc = Account(row["acc_id"], row["name"], cfg, row["added_by"])
        ok, msg = await acc.start()
        if ok:
            runtime[acc.acc_id] = acc
            loaded += 1
            print(f"  ✓  {row['name']}  id={row['acc_id'][:8]}  by={row['added_by']}")
        else:
            print(f"  ✗  {row['name']}  —  {msg}")
    print(f"{'─'*55}")
    print(f"  Khôi phục thành công: {loaded}/{len(rows)}")
    print(f"{'─'*55}\n")
    await tree.sync()
    asyncio.get_event_loop().create_task(global_log_loop())
    async with aiohttp.ClientSession() as s:
        await push_global_log(s)


@tree.command(name="thêm", description="Thêm tài khoản AFK vào hệ thống chung")
async def cmd_them(interaction: discord.Interaction, file: discord.Attachment):
    uid       = interaction.user.id
    remaining = check_cooldown(uid)
    if remaining:
        await interaction.response.send_message(
            f"⏳ Chờ **{remaining}s** trước khi dùng lệnh tiếp theo.", ephemeral=True)
        return
    set_cooldown(uid)

    if db_count() >= MAX_ACC:
        await interaction.response.send_message(
            f"Hệ thống đã đạt tối đa **{MAX_ACC} tài khoản**.", ephemeral=True)
        return
    if not file.filename.endswith(".json"):
        await interaction.response.send_message("Chỉ chấp nhận file `.json`.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        cfg = json.loads(await file.read())
    except Exception:
        await interaction.followup.send("File JSON không hợp lệ.", ephemeral=True)
        return

    token = cfg.get("token", "").strip()
    if not token:
        await interaction.followup.send("Thiếu trường `token` trong file JSON.", ephemeral=True)
        return

    name   = cfg.get("name", "").strip() or file.filename.removesuffix(".json")
    acc_id = str(uuid.uuid4())
    fpath  = os.path.join(CONFIGS_DIR, f"{acc_id}.json")

    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    acc = Account(acc_id, name, cfg, uid)
    ok, msg = await acc.start()

    if not ok:
        os.remove(fpath)
        await interaction.followup.send(f"Lỗi khởi động: **{msg}**", ephemeral=True)
        return

    runtime[acc_id] = acc
    db_insert(acc_id, name, fpath, uid)

    embed = discord.Embed(title="✅  Đã thêm tài khoản AFK", color=0x2ecc71)
    embed.add_field(name="Tên",           value=f"`{name}`",                         inline=True)
    embed.add_field(name="ID",            value=f"`{acc_id[:8]}...`",                inline=True)
    embed.add_field(name="File",          value=f"`{acc_id[:12]}....json`",          inline=True)
    embed.add_field(name="Tenant",        value=f"`{acc.tenant_id[:20]}...`",        inline=True)
    embed.add_field(name="Heartbeat",     value=f"`{acc.heartbeat_interval}s`",      inline=True)
    embed.add_field(name="Tổng hệ thống",value=f"`{db_count()}/{MAX_ACC}`",          inline=True)
    embed.set_footer(text=f"Thêm bởi {interaction.user}  •  {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    async with aiohttp.ClientSession() as s:
        await push_global_log(s)


@tree.command(name="xóa", description="Dừng và xoá tài khoản AFK (chỉ người thêm mới xoá được)")
@app_commands.describe(tài_khoản="Chọn tài khoản muốn xoá")
@app_commands.autocomplete(tài_khoản=autocomplete_acc)
async def cmd_xoa(interaction: discord.Interaction, tài_khoản: str):
    uid       = interaction.user.id
    remaining = check_cooldown(uid)
    if remaining:
        await interaction.response.send_message(
            f"⏳ Chờ **{remaining}s** trước khi dùng lệnh tiếp theo.", ephemeral=True)
        return
    set_cooldown(uid)

    acc = runtime.get(tài_khoản)
    if not acc:
        await interaction.response.send_message(
            "Không tìm thấy tài khoản. Dùng `/danh-sách` để xem.", ephemeral=True)
        return

    if acc.added_by != uid:
        await interaction.response.send_message(
            f"Bạn không phải người thêm tài khoản này (<@{acc.added_by}>).\nChỉ người thêm mới được xoá.",
            ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    row  = db_get(tài_khoản)
    name = acc.name
    await acc.stop()
    del runtime[tài_khoản]
    db_delete(tài_khoản)

    if row and os.path.exists(row["file_path"]):
        os.remove(row["file_path"])
        log.info(f"Đã xoá file: {row['file_path']}")

    embed = discord.Embed(
        title="🗑️  Đã xoá tài khoản",
        description=f"**{name}** đã dừng, config đã xoá, DB đã cập nhật.",
        color=0xe74c3c
    )
    embed.set_footer(text=f"Xoá bởi {interaction.user}  •  {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}")
    await interaction.followup.send(embed=embed, ephemeral=True)

    async with aiohttp.ClientSession() as s:
        await push_global_log(s)


@tree.command(name="danh-sách", description="Xem tất cả tài khoản AFK trong hệ thống")
async def cmd_danh_sach(interaction: discord.Interaction):
    uid       = interaction.user.id
    remaining = check_cooldown(uid)
    if remaining:
        await interaction.response.send_message(
            f"⏳ Chờ **{remaining}s** trước khi dùng lệnh tiếp theo.", ephemeral=True)
        return
    set_cooldown(uid)

    if not runtime:
        await interaction.response.send_message(
            embed=discord.Embed(title="Chưa có tài khoản nào", description="Dùng `/thêm` để bắt đầu.", color=0x95a5a6),
            ephemeral=True)
        return

    embed = discord.Embed(title=f"📋  Tài khoản AFK hệ thống  —  {len(runtime)}/{MAX_ACC}", color=0x00d4aa)
    for acc in runtime.values():
        icon = "🟢" if acc.status == "hoạt động" else "🔄" if "khởi động" in acc.status else "🔴"
        embed.add_field(
            name=f"{icon}  {acc.name}  [`{acc.acc_id[:6]}`]",
            value=(
                f"Số dư: `{acc.balance:.4f} cr`  •  Kiếm: `+{acc.earned():.4f}`\n"
                f"Uptime: `{acc.elapsed_str()}`  •  HB: `{acc.hb_rate()}%`  •  Restart: `{acc.restart_count}×`\n"
                f"Thêm bởi: <@{acc.added_by}>"
            ),
            inline=False
        )
    embed.set_footer(text="Dùng /trạng-thái để xem chi tiết từng tài khoản")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="trạng-thái", description="Xem chi tiết một tài khoản AFK")
@app_commands.describe(tài_khoản="Chọn tài khoản muốn xem")
@app_commands.autocomplete(tài_khoản=autocomplete_acc)
async def cmd_trang_thai(interaction: discord.Interaction, tài_khoản: str):
    uid       = interaction.user.id
    remaining = check_cooldown(uid)
    if remaining:
        await interaction.response.send_message(
            f"⏳ Chờ **{remaining}s** trước khi dùng lệnh tiếp theo.", ephemeral=True)
        return
    set_cooldown(uid)

    acc = runtime.get(tài_khoản)
    if not acc:
        await interaction.response.send_message("Không tìm thấy tài khoản.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    per_min = await acc.fetch_per_minute()
    icon    = "🟢" if acc.status == "hoạt động" else "🔄" if "khởi động" in acc.status else "🔴"
    row     = db_get(tài_khoản)

    embed = discord.Embed(title=f"{icon}  {acc.name}",
                          color=0x2ecc71 if acc.status == "hoạt động" else 0xe67e22)
    embed.add_field(name="Trạng thái",  value=f"`{acc.status}`",                  inline=True)
    embed.add_field(name="Restart",     value=f"`{acc.restart_count}×`",           inline=True)
    embed.add_field(name="ID",          value=f"`{acc.acc_id[:8]}...`",            inline=True)
    embed.add_field(name="Số dư",       value=f"`{acc.balance:.4f} cr`",           inline=True)
    embed.add_field(name="Kiếm được",   value=f"`+{acc.earned():.4f} cr`",         inline=True)
    embed.add_field(name="Tốc độ",      value=f"`{per_min} cr/min`",               inline=True)
    embed.add_field(name="Uptime",      value=f"`{acc.elapsed_str()}`",            inline=True)
    embed.add_field(name="Heartbeat",   value=f"`{acc.hb_rate()}%`",               inline=True)
    embed.add_field(name="HB OK/Fail",  value=f"`{acc.hb_ok} / {acc.hb_fail}`",   inline=True)
    embed.add_field(name="Tenant ID",   value=f"`{acc.tenant_id}`",                inline=False)
    embed.add_field(name="Thêm bởi",    value=f"<@{acc.added_by}>",               inline=True)
    if row:
        embed.add_field(name="Thêm lúc",value=f"`{row['added_at']}`",             inline=True)
        embed.add_field(name="File",    value=f"`{os.path.basename(row['file_path'])[:20]}...`", inline=True)
    embed.set_footer(text=f"Cập nhật lúc {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="trợ-giúp", description="Hướng dẫn sử dụng bot")
async def cmd_tro_giup(interaction: discord.Interaction):
    embed = discord.Embed(title="Altare AFK Bot  —  Hướng dẫn", color=0x00d4aa)
    embed.add_field(
        name="Bước 1  —  Lấy token",
        value=(
            "1. Mở `altare.sh` → đăng nhập\n"
            "2. Nhấn `F12` → tab **Network**\n"
            "3. Click request tới `altare.sh`\n"
            "4. Copy header **Authorization** (`Bearer eyJ...`)"
        ), inline=False
    )
    embed.add_field(
        name="Bước 2  —  Tạo file config.json",
        value=(
            "```json\n{\n"
            '  "name": "Tên tài khoản",\n'
            '  "token": "Bearer eyJ...",\n'
            '  "tenant_id": "",\n'
            '  "discord_webhook": "https://discord.com/api/webhooks/...",\n'
            '  "heartbeat_interval": 30,\n'
            '  "stats_interval": 60,\n'
            '  "notify_interval_seconds": 10\n'
            "}\n```"
            "`tenant_id` để trống — bot tự tìm."
        ), inline=False
    )
    embed.add_field(name="Bước 3", value="Dùng `/thêm` và đính kèm file JSON.", inline=False)
    embed.add_field(
        name="Lệnh",
        value=(
            "`/thêm`         Thêm tài khoản vào hệ thống\n"
            "`/xóa`          Xoá acc *(chỉ người thêm mới xoá được)*\n"
            "`/danh-sách`    Xem toàn bộ acc đang chạy\n"
            "`/trạng-thái`   Chi tiết một acc\n"
            "`/trợ-giúp`     Hiện hướng dẫn này"
        ), inline=False
    )
    embed.add_field(
        name="Hệ thống chung",
        value=(
            f"— Config lưu trong `configs/` tên file UUID random (không trùng)\n"
            f"— `afk.db` ghi lại: acc ID, tên, file, người thêm, thời gian\n"
            f"— Chỉ người thêm mới xoá được acc của mình\n"
            f"— Cooldown: **{CMD_COOLDOWN}s** mỗi người mỗi lệnh\n"
            f"— Global log cập nhật mỗi **{GLOBAL_LOG_INTERVAL}s**\n"
            f"— Giới hạn: **{MAX_ACC} acc** toàn hệ thống"
        ), inline=False
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


client.run(BOT_TOKEN)
