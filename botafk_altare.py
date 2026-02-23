import discord
from discord import app_commands
import requests
import threading
import asyncio
import json
import time
import sqlite3
import os
import uuid
from getpass import getpass
from datetime import datetime, timezone

def _clear():
    os.system("cls" if os.name == "nt" else "clear")

BOT_TOKEN = getpass("Nhập token bot Discord: ").strip()
_clear()
print("Token đã nhận. Đang khởi động bot...")

BASE_URL     = "https://altare.sh"
MAX_ACC      = 50
RETRY_DELAY  = 30
MAX_HB_FAIL  = 5
CHANNEL_ID   = 1475485961881125006
CONFIG_DIR   = "data/config"
DB_PATH      = "data/afk.db"

os.makedirs(CONFIG_DIR, exist_ok=True)

intents            = discord.Intents.default()
client             = discord.Client(intents=intents)
tree               = app_commands.CommandTree(client)
runtime            = {}
channel_message_id = None


def cfg_path(filename):
    return os.path.join(CONFIG_DIR, filename)

def cfg_save(cfg):
    fname = cfg.get("_file") or f"{uuid.uuid4().hex[:8]}.json"
    cfg["_file"] = fname
    with open(cfg_path(fname), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if k != "_file"}, f, ensure_ascii=False, indent=2)
    return fname

def cfg_delete(fname):
    try:
        os.remove(cfg_path(fname))
    except:
        pass


def db_init():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            user_id INTEGER,
            name    TEXT,
            file    TEXT,
            PRIMARY KEY (user_id, name)
        )
    """)
    conn.commit()
    conn.close()

def db_save(user_id, name, fname):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO accounts VALUES (?, ?, ?)",
        (user_id, name, fname)
    )
    conn.commit()
    conn.close()

def db_delete(user_id, name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM accounts WHERE user_id=? AND name=?", (user_id, name))
    conn.commit()
    conn.close()

def db_count_all():
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    conn.close()
    return count

def db_all():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT user_id, name, file FROM accounts").fetchall()
    conn.close()
    return [{"user_id": r[0], "name": r[1], "file": r[2]} for r in rows]


class Account:
    def __init__(self, user_id, name, cfg, fname=""):
        self.user_id            = user_id
        self.name               = name
        self.cfg                = cfg
        self.fname              = fname
        self.token              = cfg["token"] if cfg["token"].startswith("Bearer ") else f"Bearer {cfg['token']}"
        self.tenant_id          = cfg.get("tenant_id", "").strip()
        self.heartbeat_interval = cfg.get("heartbeat_interval", 30)
        self.stats_interval     = cfg.get("stats_interval", 60)
        self.running            = False
        self.session_start      = None
        self.credits_start      = 0
        self.balance            = 0
        self.hb_ok              = 0
        self.hb_fail            = 0
        self.restart_count      = 0
        self.status             = "đang khởi động"

    def h(self):
        h = {
            "Authorization": self.token,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Origin":        BASE_URL,
            "Referer":       f"{BASE_URL}/billing/rewards/afk",
            "User-Agent":    "Mozilla/5.0"
        }
        if self.tenant_id:
            h["altare-selected-tenant-id"] = self.tenant_id
        return h

    def detect_tenant(self):
        try:
            r = requests.get(f"{BASE_URL}/api/tenants", headers=self.h(), timeout=10)
            if r.status_code == 200:
                data  = r.json()
                items = data.get("items", data) if isinstance(data, dict) else data
                if items:
                    return items[0].get("id") or items[0].get("tenantId")
        except:
            pass
        return None

    def fetch_balance(self):
        try:
            r = requests.get(f"{BASE_URL}/api/tenants", headers=self.h(), timeout=10)
            if r.status_code == 200:
                items = r.json()
                items = items.get("items", items) if isinstance(items, dict) else items
                for item in items:
                    if item.get("id") == self.tenant_id:
                        c = item.get("creditsCents")
                        return round(c / 100, 4) if c is not None else None
                if items:
                    c = items[0].get("creditsCents")
                    return round(c / 100, 4) if c is not None else None
        except:
            pass
        return None

    def fetch_per_minute(self):
        try:
            r = requests.get(f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards", headers=self.h(), timeout=10)
            if r.status_code == 200:
                data = r.json()
                afk  = data.get("afk") if isinstance(data.get("afk"), dict) else {}
                return afk.get("perMinute") or data.get("perMinute") or 0.35
        except:
            pass
        return 0.35

    def do_heartbeat(self):
        try:
            r = requests.post(
                f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/heartbeat",
                headers=self.h(), json={}, timeout=10
            )
            return r.status_code in (200, 201, 204)
        except:
            return False

    def api_start(self):
        try:
            r = requests.post(
                f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/start",
                headers=self.h(), json={}, timeout=10
            )
            return r.status_code in (200, 201, 204)
        except:
            return False

    def api_stop(self):
        try:
            requests.post(
                f"{BASE_URL}/api/tenants/{self.tenant_id}/rewards/afk/stop",
                headers=self.h(), json={}, timeout=10
            )
        except:
            pass

    def _ts(self):
        return datetime.now().strftime("%H:%M:%S")

    def log(self, msg):
        print(f"[{self._ts()}] [{self.name}] {msg}")

    def _write_tenant_to_file(self):
        if not self.fname:
            return
        try:
            fpath = cfg_path(self.fname)
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            data["tenant_id"] = self.tenant_id
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            pass

    def _reset_state(self):
        self.hb_ok         = 0
        self.hb_fail       = 0
        self.session_start = datetime.now()
        self.credits_start = 0
        self.status        = "đang khởi động"

    def _do_restart(self):
        self.log("phiên bị lỗi — đang thử khởi động lại...")
        self.status = "đang khởi động lại"
        self.api_stop()
        asyncio.run_coroutine_threadsafe(push_channel_status(), client.loop)
        time.sleep(RETRY_DELAY)

        for attempt in range(1, 6):
            self.log(f"thử lần {attempt}/5...")
            self._reset_state()
            if not self.tenant_id:
                self.tenant_id = self.detect_tenant()
            if self.tenant_id and self.api_start():
                self.restart_count += 1
                self.status = "hoạt động"
                self.log(f"khởi động lại thành công (lần {self.restart_count})")
                asyncio.run_coroutine_threadsafe(push_channel_status(), client.loop)
                return True
            time.sleep(RETRY_DELAY)

        self.status  = "lỗi — không thể khởi động lại"
        self.running = False
        self.log("đã thử 5 lần nhưng thất bại, dừng hẳn")
        asyncio.run_coroutine_threadsafe(push_channel_status(), client.loop)
        return False

    def _loop_heartbeat(self):
        consecutive_fail = 0
        while self.running:
            if self.do_heartbeat():
                self.hb_ok += 1
                consecutive_fail = 0
            else:
                self.hb_fail += 1
                consecutive_fail += 1
                self.log(f"heartbeat thất bại ({consecutive_fail}/{MAX_HB_FAIL})")
                if consecutive_fail >= MAX_HB_FAIL:
                    self.log(f"heartbeat thất bại {MAX_HB_FAIL} lần liên tiếp — trigger restart")
                    consecutive_fail = 0
                    if not self._do_restart():
                        break
            time.sleep(self.heartbeat_interval)

    def _loop_stats(self):
        while self.running:
            bal = self.fetch_balance()
            if bal is not None:
                if not self.credits_start:
                    self.credits_start = bal
                self.balance = bal
                earned  = round(bal - self.credits_start, 4)
                elapsed = str(datetime.now() - self.session_start).split(".")[0]
                hb_rate = round(self.hb_ok / max(self.hb_ok + self.hb_fail, 1) * 100)
                self.log(f"{bal:.4f} cr  +{earned:.4f}  {elapsed}  hb {hb_rate}%  restart×{self.restart_count}")
            asyncio.run_coroutine_threadsafe(push_channel_status(), client.loop)
            time.sleep(self.stats_interval)

    def _loop_sse(self):
        raw  = self.token.replace("Bearer ", "")
        url  = f"https://api.altare.sh/subscribe?token={raw}"
        hdrs = {
            "Accept":        "text/event-stream",
            "Cache-Control": "no-cache",
            "Authorization": self.token,
            "Origin":        BASE_URL,
            "User-Agent":    "Mozilla/5.0"
        }
        while self.running:
            try:
                with requests.get(url, headers=hdrs, stream=True, timeout=(15, None)) as r:
                    if r.status_code == 200:
                        for _ in r.iter_lines(chunk_size=1):
                            if not self.running:
                                break
                    else:
                        time.sleep(15)
            except:
                if self.running:
                    time.sleep(15)
            if self.running:
                time.sleep(5)

    def start(self):
        if not self.tenant_id:
            self.tenant_id = self.detect_tenant()
        if not self.tenant_id:
            return False, "Không tìm được tenant ID — kiểm tra lại token."
        if not self.api_start():
            return False, "Gọi API start AFK thất bại."

        self._write_tenant_to_file()
        self.running       = True
        self.session_start = datetime.now()
        self.status        = "hoạt động"

        for fn in [self._loop_sse, self._loop_heartbeat, self._loop_stats]:
            threading.Thread(target=fn, daemon=True).start()

        self.log("đã bắt đầu")
        return True, "OK"

    def stop(self):
        self.running = False
        self.api_stop()
        self.log("đã dừng")


def build_channel_embed():
    all_accs = []
    for uid, accs in runtime.items():
        for name, acc in accs.items():
            all_accs.append((uid, name, acc))

    embed = discord.Embed(
        title=f"📊  Altare AFK — Tổng quan  ({len(all_accs)}/{MAX_ACC})",
        color=0x00d4aa,
        timestamp=datetime.now(tz=timezone.utc)
    )

    if not all_accs:
        embed.description = "Chưa có tài khoản nào đang chạy."
        return embed

    for uid, name, acc in all_accs:
        earned  = round(acc.balance - acc.credits_start, 4) if acc.credits_start else 0
        elapsed = str(datetime.now() - acc.session_start).split(".")[0] if acc.session_start else "?"
        hb_rate = round(acc.hb_ok / max(acc.hb_ok + acc.hb_fail, 1) * 100)
        icon    = "🟢" if acc.status == "hoạt động" else "🔄" if "khởi động" in acc.status else "🔴"
        embed.add_field(
            name=f"{icon}  {name}",
            value=(
                f"Số dư: `{acc.balance:.4f} cr`  +`{earned:.4f}`\n"
                f"Uptime: `{elapsed}`  HB: `{hb_rate}%`  Restart: `{acc.restart_count}×`"
            ),
            inline=False
        )

    embed.set_footer(text=f"Cập nhật lúc {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}")
    return embed


async def push_channel_status():
    global channel_message_id
    ch = client.get_channel(CHANNEL_ID)
    if ch is None:
        return

    embed = build_channel_embed()
    view  = discord.ui.View(timeout=None)
    btn   = discord.ui.Button(label="Làm mới", style=discord.ButtonStyle.secondary, custom_id="refresh_status")
    view.add_item(btn)

    try:
        if channel_message_id is None:
            msg = await ch.send(embed=embed, view=view)
            channel_message_id = msg.id
        else:
            try:
                msg = await ch.fetch_message(channel_message_id)
                await msg.edit(embed=embed, view=view)
            except discord.NotFound:
                msg = await ch.send(embed=embed, view=view)
                channel_message_id = msg.id
    except Exception as e:
        print(f"[push_channel_status] lỗi: {e}")


async def autocomplete_acc(interaction: discord.Interaction, current: str):
    all_names = []
    for accs in runtime.values():
        all_names.extend(accs.keys())
    return [
        app_commands.Choice(name=n, value=n)
        for n in all_names if current.lower() in n.lower()
    ][:25]


@client.event
async def on_ready():
    db_init()
    rows   = db_all()
    loaded = 0

    print(f"\n{'─'*45}")
    print(f"  Bot: {client.user}")
    print(f"  Đang khôi phục {len(rows)} tài khoản từ data/config/...")
    print(f"{'─'*45}")

    for row in rows:
        uid   = row["user_id"]
        name  = row["name"]
        fname = row["file"]
        fpath = cfg_path(fname)

        if not os.path.exists(fpath):
            print(f"  ✗  {name}  —  file {fname} không tồn tại, bỏ qua")
            continue

        try:
            with open(fpath, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"  ✗  {name}  —  lỗi đọc file: {e}")
            continue

        acc = Account(uid, name, cfg, fname=fname)
        ok, msg = acc.start()
        if ok:
            runtime.setdefault(uid, {})[name] = acc
            loaded += 1
            print(f"  ✓  {name}  (file: {fname})")
        else:
            print(f"  ✗  {name}  —  {msg}")

    print(f"{'─'*45}")
    print(f"  Khôi phục thành công: {loaded}/{len(rows)}")
    print(f"{'─'*45}\n")

    await tree.sync()
    await push_channel_status()


@client.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        if interaction.data.get("custom_id") == "refresh_status":
            await interaction.response.defer()
            await push_channel_status()
            return
    await client.process_application_commands(interaction)


@tree.command(name="thêm", description="Thêm tài khoản AFK mới — nhập trực tiếp (tối đa 50)")
@app_commands.describe(
    tên="Tên tài khoản hiển thị",
    token="Token Bearer (Bearer eyJ... hoặc chỉ eyJ...)",
    heartbeat="Chu kỳ heartbeat tính bằng giây (mặc định 30)",
    stats="Chu kỳ cập nhật số dư tính bằng giây (mặc định 60)"
)
async def cmd_them(
    interaction: discord.Interaction,
    tên: str,
    token: str,
    heartbeat: int = 30,
    stats: int = 60
):
    uid  = interaction.user.id
    name = tên.strip()

    if db_count_all() >= MAX_ACC:
        await interaction.response.send_message(
            f"Đã đạt tối đa **{MAX_ACC} tài khoản** toàn hệ thống.", ephemeral=True)
        return

    if not name:
        await interaction.response.send_message("Tên không được để trống.", ephemeral=True)
        return

    for accs in runtime.values():
        if name in accs:
            await interaction.response.send_message(
                f"Tên `{name}` đã tồn tại. Chọn tên khác.", ephemeral=True)
            return

    token = token.strip()
    if not token:
        await interaction.response.send_message("Token không được để trống.", ephemeral=True)
        return

    cfg = {
        "name":               name,
        "token":              token,
        "tenant_id":          "",
        "heartbeat_interval": heartbeat,
        "stats_interval":     stats
    }

    await interaction.response.defer(ephemeral=True)

    fname = f"{uuid.uuid4().hex[:8]}.json"
    acc   = Account(uid, name, cfg, fname=fname)
    ok, msg = await asyncio.get_event_loop().run_in_executor(None, acc.start)

    if not ok:
        await interaction.followup.send(f"Lỗi khởi động: **{msg}**", ephemeral=True)
        return

    cfg["tenant_id"] = acc.tenant_id
    with open(cfg_path(fname), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    runtime.setdefault(uid, {})[name] = acc
    db_save(uid, name, fname)

    slot_con_lai = MAX_ACC - db_count_all()
    embed = discord.Embed(title="✅  Đã thêm tài khoản AFK", color=0x2ecc71)
    embed.add_field(name="Tên",          value=f"`{name}`",                   inline=True)
    embed.add_field(name="Tenant",       value=f"`{acc.tenant_id[:18]}...`",   inline=True)
    embed.add_field(name="Slot còn lại", value=f"`{slot_con_lai}/{MAX_ACC}`",  inline=True)
    embed.add_field(name="Heartbeat",    value=f"`{acc.heartbeat_interval}s`", inline=True)
    embed.add_field(name="Stats",        value=f"`{acc.stats_interval}s`",     inline=True)
    embed.add_field(name="File config",  value=f"`data/config/{fname}`",       inline=False)
    embed.set_footer(text="Tự khôi phục khi bot restart")
    await interaction.followup.send(embed=embed, ephemeral=True)
    await push_channel_status()


@tree.command(name="xóa", description="Dừng và xoá một tài khoản AFK")
@app_commands.describe(tài_khoản="Tên tài khoản muốn xoá")
@app_commands.autocomplete(tài_khoản=autocomplete_acc)
async def cmd_xoa(interaction: discord.Interaction, tài_khoản: str):
    found_uid  = None
    found_accs = None
    for u, a in runtime.items():
        if tài_khoản in a:
            found_uid  = u
            found_accs = a
            break

    if found_uid is None:
        await interaction.response.send_message(
            f"Không tìm thấy `{tài_khoản}`.", ephemeral=True)
        return

    acc = found_accs[tài_khoản]
    acc.stop()
    cfg_delete(acc.fname)
    del found_accs[tài_khoản]
    if not found_accs:
        runtime.pop(found_uid, None)

    db_delete(found_uid, tài_khoản)

    embed = discord.Embed(
        title="Đã xoá tài khoản",
        description=f"**{tài_khoản}** đã dừng, xoá DB và xoá `data/config/{acc.fname}`.",
        color=0xe74c3c
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    await push_channel_status()


@tree.command(name="danh-sách", description="Xem tất cả tài khoản AFK đang chạy")
async def cmd_danh_sach(interaction: discord.Interaction):
    all_accs = []
    for uid, accs in runtime.items():
        for name, acc in accs.items():
            all_accs.append((uid, name, acc))

    if not all_accs:
        embed = discord.Embed(
            title="Chưa có tài khoản nào",
            description="Dùng `/thêm` để bắt đầu.",
            color=0x95a5a6
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(
        title=f"Tài khoản AFK — {len(all_accs)}/{MAX_ACC}",
        color=0x00d4aa
    )
    for uid, name, acc in all_accs:
        earned  = round(acc.balance - acc.credits_start, 4) if acc.credits_start else 0
        elapsed = str(datetime.now() - acc.session_start).split(".")[0] if acc.session_start else "?"
        hb_rate = round(acc.hb_ok / max(acc.hb_ok + acc.hb_fail, 1) * 100)
        icon    = "🟢" if acc.status == "hoạt động" else "🔄" if "khởi động" in acc.status else "🔴"
        embed.add_field(
            name=f"{icon}  {name}",
            value=(
                f"Số dư: `{acc.balance:.4f} cr`  •  Kiếm: `+{earned:.4f}`\n"
                f"Uptime: `{elapsed}`  •  HB: `{hb_rate}%`  •  Restart: `{acc.restart_count}×`"
            ),
            inline=False
        )
    embed.set_footer(text="Dùng /trạng-thái để xem chi tiết")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="trạng-thái", description="Xem chi tiết một tài khoản AFK")
@app_commands.describe(tài_khoản="Tên tài khoản muốn xem")
@app_commands.autocomplete(tài_khoản=autocomplete_acc)
async def cmd_trang_thai(interaction: discord.Interaction, tài_khoản: str):
    acc = None
    for accs in runtime.values():
        if tài_khoản in accs:
            acc = accs[tài_khoản]
            break

    if acc is None:
        await interaction.response.send_message(
            f"Không tìm thấy `{tài_khoản}`.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    earned  = round(acc.balance - acc.credits_start, 4) if acc.credits_start else 0
    elapsed = str(datetime.now() - acc.session_start).split(".")[0] if acc.session_start else "?"
    hb_rate = round(acc.hb_ok / max(acc.hb_ok + acc.hb_fail, 1) * 100)
    per_min = await asyncio.get_event_loop().run_in_executor(None, acc.fetch_per_minute)
    icon    = "🟢" if acc.status == "hoạt động" else "🔄" if "khởi động" in acc.status else "🔴"

    embed = discord.Embed(
        title=f"{icon}  {tài_khoản}",
        color=0x2ecc71 if acc.status == "hoạt động" else 0xe67e22
    )
    embed.add_field(name="Trạng thái",    value=f"`{acc.status}`",                inline=True)
    embed.add_field(name="Khởi động lại", value=f"`{acc.restart_count} lần`",     inline=True)
    embed.add_field(name="\u200b",        value="\u200b",                           inline=True)
    embed.add_field(name="Số dư",         value=f"`{acc.balance:.4f} cr`",         inline=True)
    embed.add_field(name="Kiếm được",     value=f"`+{earned:.4f} cr`",             inline=True)
    embed.add_field(name="Tốc độ",        value=f"`{per_min} cr/min`",             inline=True)
    embed.add_field(name="Uptime",        value=f"`{elapsed}`",                    inline=True)
    embed.add_field(name="Heartbeat",     value=f"`{hb_rate}% OK`",                inline=True)
    embed.add_field(name="HB OK / Fail",  value=f"`{acc.hb_ok} / {acc.hb_fail}`", inline=True)
    embed.add_field(name="Tenant ID",     value=f"`{acc.tenant_id}`",              inline=False)
    embed.add_field(name="File config",   value=f"`data/config/{acc.fname}`",      inline=False)
    embed.set_footer(text=f"Cập nhật lúc {datetime.now().strftime('%H:%M:%S  %d/%m/%Y')}")

    await interaction.followup.send(embed=embed, ephemeral=True)


client.run(BOT_TOKEN)
