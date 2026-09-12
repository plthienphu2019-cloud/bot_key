# ============================================
# TPHUDZ KEY BOT — RENDER READY (Webhook Mode)
# ============================================
import logging
import sqlite3
import secrets
import string
import time
import os
import threading
import asyncio
import urllib.request

from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommand, MenuButtonCommands, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ============================================
# CONFIG
# ============================================
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN",
    "8976870037:AAGuBLfCx8VSTms00hCUECNfQ2yjN0_GqBg"
)
DB_PATH = "tphudz.db"
PORT = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

ADMINS = {
    "tphu2012":   {"password": "2012/21/09",  "role": "super", "name": "Admin Chính"},
    "minhlam900": {"password": "minhlam900$", "role": "sub",   "name": "Admin Phụ"},
}

# ============================================
# KEY TYPES
# ============================================
KEY_TYPES = {
    "bac":    {"name": "Key Bạc",   "prefix": "TPTOOL_VIP1",           "role": "VIP1"},
    "vang":   {"name": "Key Vàng",  "prefix": "TPTOOL_VIP3",           "role": "VIP3"},
    "super":  {"name": "Key Super", "prefix": "TPTOOL_VIP_PRENIUM",    "role": "PREMIUM"},
}

DURATIONS = {
    "24h":  {"name": "1 Ngày (24h)",   "hours": 24},
    "72h":  {"name": "3 Ngày (72h)",   "hours": 72},
    "168h": {"name": "1 Tuần (168h)",  "hours": 168},
    "720h": {"name": "1 Tháng (720h)", "hours": 720},
}

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
WAITING = {}

# ============================================
# DATABASE
# ============================================
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            tg_id INTEGER PRIMARY KEY,
            username TEXT, display TEXT, code TEXT,
            admin_user TEXT, admin_role TEXT, login_time INTEGER
        );
        CREATE TABLE IF NOT EXISTS key_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER, admin_user TEXT,
            key_value TEXT, key_type TEXT, duration TEXT,
            status TEXT DEFAULT 'pending',
            created INTEGER, approved_by TEXT, approved_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER, channel_id TEXT, channel_name TEXT,
            member_count INTEGER, linked_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER, admin_user TEXT, content TEXT, amount INTEGER,
            status TEXT DEFAULT 'pending', created INTEGER,
            approved_by TEXT, approved_at INTEGER
        );
        """)


def save_user(tg_id, username, display, admin_user, role):
    code = "".join(secrets.choice(string.digits) for _ in range(8))
    with db() as c:
        row = c.execute("SELECT code FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        if row:
            code = row["code"]
            c.execute("""UPDATE users SET username=?, display=?, admin_user=?,
                admin_role=?, login_time=? WHERE tg_id=?""",
                (username, display, admin_user, role, int(time.time()), tg_id))
        else:
            c.execute("""INSERT INTO users (tg_id, username, display, code,
                admin_user, admin_role, login_time) VALUES (?,?,?,?,?,?,?)""",
                (tg_id, username, display, code, admin_user, role, int(time.time())))
    return code


def get_user(tg_id):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()


def del_user(tg_id):
    with db() as c:
        c.execute("DELETE FROM users WHERE tg_id=?", (tg_id,))


def create_key_req(tg_id, admin_user, key_value, key_type, duration):
    with db() as c:
        cur = c.execute("""INSERT INTO key_requests
            (tg_id, admin_user, key_value, key_type, duration, created)
            VALUES (?,?,?,?,?,?)""",
            (tg_id, admin_user, key_value, key_type, duration, int(time.time())))
        return cur.lastrowid


def get_key_req(req_id):
    with db() as c:
        return c.execute("SELECT * FROM key_requests WHERE id=?", (req_id,)).fetchone()


def approve_key(req_id, approver):
    with db() as c:
        c.execute("""UPDATE key_requests SET status='approved',
            approved_by=?, approved_at=? WHERE id=?""",
            (approver, int(time.time()), req_id))


def reject_key(req_id, approver):
    with db() as c:
        c.execute("""UPDATE key_requests SET status='rejected',
            approved_by=?, approved_at=? WHERE id=?""",
            (approver, int(time.time()), req_id))


def add_channel(tg_id, channel_id, channel_name, members):
    with db() as c:
        c.execute("""INSERT INTO channels
            (tg_id, channel_id, channel_name, member_count, linked_at)
            VALUES (?,?,?,?,?)""",
            (tg_id, channel_id, channel_name, members, int(time.time())))


def list_bills():
    with db() as c:
        return c.execute("SELECT * FROM bills WHERE status='pending' ORDER BY created").fetchall()


def approve_bill(bill_id, approver):
    with db() as c:
        c.execute("""UPDATE bills SET status='approved',
            approved_by=?, approved_at=? WHERE id=?""",
            (approver, int(time.time()), bill_id))


# ============================================
# KEY GENERATOR
# ============================================
def _rand_upper(n):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def gen_key(key_type: str) -> str:
    """Sinh key theo đúng format yêu cầu"""
    if key_type == "bac":
        # TPTOOL_VIP1_XXXXX_XXXXX_XXXX
        return f"TPTOOL_VIP1_{_rand_upper(5)}_{_rand_upper(5)}_{_rand_upper(4)}"
    elif key_type == "vang":
        # TPTOOL_VIP3_XXXX_XXXXXX_XXXX
        return f"TPTOOL_VIP3_{_rand_upper(4)}_{_rand_upper(6)}_{_rand_upper(4)}"
    elif key_type == "super":
        # TPTOOL_VIP_PRENIUM_XXX_XXXX_XXX_XXX_XXXX
        return (f"TPTOOL_VIP_PRENIUM_{_rand_upper(3)}_{_rand_upper(4)}_"
                f"{_rand_upper(3)}_{_rand_upper(3)}_{_rand_upper(4)}")
    return f"TPTOOL_UNKNOWN_{_rand_upper(8)}"


# ============================================
# KEYBOARDS
# ============================================
def main_menu(role):
    if role == "super":
        rows = [
            [KeyboardButton("🔑 Lấy key VIP")],
            [KeyboardButton("🔐 Đổi mật khẩu")],
            [KeyboardButton("📡 Thêm Kênh")],
            [KeyboardButton("💳 Duyệt Bill")],
            [KeyboardButton("👤 Hồ sơ cá nhân")],
            [KeyboardButton("⬅️ Quay lại menu")],
        ]
    elif role == "sub":
        rows = [
            [KeyboardButton("🔑 Lấy key VIP (chờ duyệt)")],
            [KeyboardButton("🔐 Đổi mật khẩu")],
            [KeyboardButton("👤 Hồ sơ cá nhân")],
            [KeyboardButton("⬅️ Quay lại menu")],
        ]
    else:
        rows = [[KeyboardButton("⬅️ Quay lại menu")]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def back_only_kb():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⬅️ Quay lại menu")]],
        resize_keyboard=True
    )


def key_type_kb():
    """Menu chọn loại key"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("🥈 Key bạc")],
        [KeyboardButton("🥇 Key vàng")],
        [KeyboardButton("💎 Key Super")],
        [KeyboardButton("⬅️ Quay lại menu")],
    ], resize_keyboard=True)


def duration_kb():
    """Menu chọn thời hạn"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("⏱ 1 ngày 24h")],
        [KeyboardButton("⏱ 3 ngày 72h")],
        [KeyboardButton("⏱ 1 tuần 168h")],
        [KeyboardButton("⏱ 1 tháng 720h")],
        [KeyboardButton("⬅️ Quay lại menu")],
    ], resize_keyboard=True)


async def _cleanup_msgs(ctx, uid):
    old = WAITING.pop(f"del_{uid}", [])
    for mid in old:
        try:
            await ctx.bot.delete_message(uid, mid)
        except Exception:
            pass


async def send_auto_delete(msg, delay=40):
    """Tự động xoá tin nhắn sau `delay` giây"""
    async def _del():
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass
    asyncio.create_task(_del())


# ============================================
# HANDLERS
# ============================================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 *Để lấy key vui lòng đăng nhập tài khoản admin đã được cấp*\n\n"
        "`/login <Tên đăng nhập> <Mật khẩu>`\n\n"
        "Ví dụ: `/login tphudz 123456`\n\n"
        "*Tài khoản admin:*\n"
        "👤 Admin phụ:\n"
        "  • Tài khoản: `minhlam900`\n"
        "  • Mật khẩu: `minhlam900$`\n\n"
        "👑 Admin chính:\n"
        "  • Tài khoản: `tphu2012`\n"
        "  • Mật khẩu: `2012/21/09`",
        parse_mode="Markdown",
    )


async def cmd_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("❌ Cú pháp: `/login <user> <pass>`", parse_mode="Markdown")
        return

    username, password = args[0], args[1]
    acc = ADMINS.get(username)
    if not acc or acc["password"] != password:
        await update.message.reply_text("❌ Sai tài khoản hoặc mật khẩu.")
        return

    code = save_user(user.id, user.username or "", user.full_name, username, acc["role"])
    role_name = "Admin Chính 👑" if acc["role"] == "super" else "Admin Phụ 👤"
    await update.message.reply_text(
        f"✅ Đăng nhập thành công!\n"
        f"🎭 Vai trò: *{role_name}*\n"
        f"🆔 Mã định danh: `{code}`\n\n"
        f"Sử dụng menu bên dưới 👇",
        parse_mode="Markdown",
        reply_markup=main_menu(acc["role"]),
    )


async def cmd_logout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    del_user(update.effective_user.id)
    await update.message.reply_text("👋 Đã đăng xuất.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — Bắt đầu\n/login — Đăng nhập\n/logout — Đăng xuất\n/cancel — Hủy"
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    WAITING.pop(uid, None)
    await _cleanup_msgs(ctx, uid)
    await update.message.reply_text("❌ Đã hủy.")


# ============================================
# MENU HANDLER
# ============================================
async def handle_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id
    user = get_user(uid)
    if not user:
        await update.message.reply_text("🔐 Vui lòng /login trước.")
        return

    role = user["admin_role"]

    # ===== QUAY LẠI MENU =====
    if text == "⬅️ Quay lại menu":
        WAITING.pop(uid, None)
        await _cleanup_msgs(ctx, uid)
        await update.message.reply_text("📋 Menu chính:", reply_markup=main_menu(role))
        return

    # ===== LẤY KEY VIP =====
    if text in ("🔑 Lấy key VIP", "🔑 Lấy key VIP (chờ duyệt)"):
        WAITING[uid] = "choose_type"
        prompt = await update.message.reply_text(
            "🔑 *CHỌN LOẠI KEY*\n\n"
            "🥈 *Key bạc*: VIP1\n"
            "🥇 *Key vàng*: VIP3\n"
            "💎 *Key Super*: PREMIUM\n\n"
            "👉 Chọn loại key bên dưới:",
            parse_mode="Markdown",
            reply_markup=key_type_kb()
        )
        WAITING[f"del_{uid}"] = [update.message.message_id, prompt.message_id]
        return

    # ===== CHỌN LOẠI KEY =====
    if uid in WAITING and WAITING[uid] == "choose_type":
        if text == "🥈 Key bạc":
            WAITING[uid] = {"type": "bac", "stage": "duration"}
        elif text == "🥇 Key vàng":
            WAITING[uid] = {"type": "vang", "stage": "duration"}
        elif text == "💎 Key Super":
            WAITING[uid] = {"type": "super", "stage": "duration"}
        else:
            await update.message.reply_text("❓ Chọn 1 trong 3 loại key.")
            return

        # Xoá prompt cũ
        await _cleanup_msgs(ctx, uid)

        prompt = await update.message.reply_text(
            f"⏱ *CHỌN THỜI HẠN* — {KEY_TYPES[WAITING[uid]['type']]['name']}\n\n"
            "• 1 ngày → 24h\n"
            "• 3 ngày → 72h\n"
            "• 1 tuần → 168h\n"
            "• 1 tháng → 720h\n\n"
            "👉 Chọn thời hạn:",
            parse_mode="Markdown",
            reply_markup=duration_kb()
        )
        WAITING[f"del_{uid}"] = [update.message.message_id, prompt.message_id]
        return

    # ===== CHỌN THỜI HẠN =====
    if uid in WAITING and isinstance(WAITING[uid], dict) and WAITING[uid].get("stage") == "duration":
        dur_map = {
            "⏱ 1 ngày 24h":   "24h",
            "⏱ 3 ngày 72h":   "72h",
            "⏱ 1 tuần 168h":  "168h",
            "⏱ 1 tháng 720h": "720h",
        }
        if text not in dur_map:
            await update.message.reply_text("❓ Chọn 1 trong 4 thời hạn.")
            return

        key_type = WAITING[uid]["type"]
        duration = dur_map[text]

        # Sinh key
        key_value = gen_key(key_type)
        req_id = create_key_req(uid, user["admin_user"], key_value, key_type, duration)

        # Xoá prompt
        await _cleanup_msgs(ctx, uid)
        try:
            await update.message.delete()
        except Exception:
            pass

        info = KEY_TYPES[key_type]
        dur_info = DURATIONS[duration]

        # Admin chính → duyệt luôn
        if role == "super":
            approve_key(req_id, user["admin_user"])
            msg = await update.message.reply_text(
                f"✅ *KEY VIP ĐÃ TẠO*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏷 Loại: *{info['name']}*\n"
                f"⏱ Thời hạn: *{dur_info['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔑 `{key_value}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏰ {time.strftime('%H:%M:%S %d/%m/%Y')}\n"
                f"🗑 Tin nhắn sẽ tự xoá sau 40s",
                parse_mode="Markdown",
                reply_markup=main_menu(role)
            )
            await send_auto_delete(msg, 40)

        # Admin phụ → chờ duyệt
        else:
            msg = await update.message.reply_text(
                f"⏳ *YÊU CẦU ĐÃ GỬI*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏷 Loại: *{info['name']}*\n"
                f"⏱ Thời hạn: *{dur_info['name']}*\n"
                f"🔑 Key dự kiến: `{key_value}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📌 Trạng thái: *Chờ Admin Chính duyệt*\n"
                f"🗑 Tin nhắn sẽ tự xoá sau 40s",
                parse_mode="Markdown",
                reply_markup=main_menu(role)
            )
            await send_auto_delete(msg, 40)

            # Gửi cho super admin
            with db() as c:
                supers = c.execute("SELECT tg_id FROM users WHERE admin_role='super'").fetchall()
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Duyệt", callback_data=f"apk_{req_id}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"rjk_{req_id}"),
            ]])
            for s in supers:
                try:
                    await ctx.bot.send_message(
                        s["tg_id"],
                        f"🔔 *YÊU CẦU DUYỆT KEY*\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"👤 Admin phụ: `{user['admin_user']}`\n"
                        f"🆔 Mã: `{user['code']}`\n"
                        f"🏷 Loại: *{info['name']}*\n"
                        f"⏱ Thời hạn: *{dur_info['name']}*\n"
                        f"🔑 `{key_value}`",
                        parse_mode="Markdown", reply_markup=kb
                    )
                except Exception:
                    pass

        WAITING.pop(uid, None)
        return

    # ===== ĐỔI MẬT KHẨU =====
    if text == "🔐 Đổi mật khẩu":
        WAITING[uid] = "password"
        prompt = await update.message.reply_text(
            "📝 Gửi mật khẩu mới (≥6 ký tự):\n⬅️ Bấm *Quay lại menu* để hủy.",
            parse_mode="Markdown",
            reply_markup=back_only_kb()
        )
        WAITING[f"del_{uid}"] = [update.message.message_id, prompt.message_id]
        return

    # ===== THÊM KÊNH =====
    if text == "📡 Thêm Kênh":
        if role != "super":
            await update.message.reply_text("⛔ Chỉ Admin Chính.", reply_markup=back_only_kb())
            return
        WAITING[uid] = "channel"
        prompt = await update.message.reply_text(
            "⚙️ *HƯỚNG DẪN LIÊN KẾT KÊNH:*\n\n"
            "1. Thêm Bot này vào Kênh của bạn (CHỈ HỖ TRỢ KÊNH).\n"
            "2. Cấp quyền Admin (Quản trị viên) cho Bot.\n"
            "3. Lấy ID Kênh (VD: `-100123456789`) hoặc Username (VD: `@kenhcuatoi`).\n\n"
            "🛡 Hệ thống sẽ xác minh tự động.\n\n"
            "👉 Dán ID hoặc Username Kênh vào đây:",
            parse_mode="Markdown",
            reply_markup=back_only_kb()
        )
        WAITING[f"del_{uid}"] = [update.message.message_id, prompt.message_id]
        return

    # ===== DUYỆT BILL =====
    if text == "💳 Duyệt Bill":
        if role != "super":
            await update.message.reply_text("⛔ Chỉ Admin Chính.", reply_markup=back_only_kb())
            return
        bills = list_bills()
        if not bills:
            await update.message.reply_text("📭 Không có bill chờ duyệt.", reply_markup=back_only_kb())
            return
        for b in bills:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Duyệt", callback_data=f"apb_{b['id']}")
            ]])
            await update.message.reply_text(
                f"💳 *BILL #{b['id']}*\n👤 `{b['admin_user']}`\n"
                f"💰 {b['amount']:,}đ\n📝 {b['content']}",
                parse_mode="Markdown", reply_markup=kb
            )
        await update.message.reply_text("⬅️ Quay lại menu", reply_markup=back_only_kb())
        return

    # ===== HỒ SƠ =====
    if text == "👤 Hồ sơ cá nhân":
        role_name = "Admin Chính 👑" if role == "super" else "Admin Phụ 👤"
        await update.message.reply_text(
            f"👤 *HỒ SƠ CÁ NHÂN*\n\n"
            f"• Tên hiển thị: *{user['display']}*\n"
            f"• Mã định danh: `{user['code']}`\n"
            f"• Username: @{user['username'] or 'N/A'}\n"
            f"• Loại Admin: *{role_name}*",
            parse_mode="Markdown",
            reply_markup=back_only_kb()
        )
        return

    # ===== ĐANG CHỜ NHẬP (password/channel) =====
    if uid in WAITING and isinstance(WAITING[uid], str):
        state = WAITING[uid]

        if state == "password":
            if len(text) < 6:
                await update.message.reply_text("❌ Phải ≥6 ký tự. Gửi lại:")
                return
            ADMINS[user["admin_user"]]["password"] = text
            WAITING.pop(uid, None)
            try:
                await update.message.delete()
            except Exception:
                pass
            await _cleanup_msgs(ctx, uid)
            msg = await update.message.reply_text(
                "✅ Đã đổi mật khẩu thành công!\n🗑 Tự xoá sau 40s",
                reply_markup=main_menu(role)
            )
            await send_auto_delete(msg, 40)
            return

        elif state == "channel":
            try:
                target = text
                if target.lstrip("-").isdigit():
                    chat = await ctx.bot.get_chat(int(target))
                else:
                    if not target.startswith("@"):
                        target = "@" + target
                    chat = await ctx.bot.get_chat(target)

                members = await ctx.bot.get_chat_member_count(chat.id)
                add_channel(uid, str(chat.id), chat.title or "Unknown", members)
                WAITING.pop(uid, None)

                try:
                    await update.message.delete()
                except Exception:
                    pass
                await _cleanup_msgs(ctx, uid)

                msg = await update.message.reply_text(
                    f"✅ *LIÊN KẾT KÊNH THÀNH CÔNG!*\n\n"
                    f"🏢 Kênh: *{chat.title}*\n"
                    f"🆔 ID: `{chat.id}`\n"
                    f"👥 Số thành viên: *{members}*\n\n"
                    f"⭐ Đã cấu hình đây là kênh nhận thông báo duy nhất của bạn.\n\n"
                    f"✉️ Bot vừa gửi thông báo kiểm tra vào Kênh!\n"
                    f"🗑 Tự xoá sau 40s",
                    parse_mode="Markdown",
                    reply_markup=main_menu(role)
                )
                await send_auto_delete(msg, 40)
                try:
                    await ctx.bot.send_message(
                        chat.id,
                        f"✅ Bot liên kết thành công!\n👤 {user['admin_user']}"
                    )
                except Exception:
                    pass
            except Exception as e:
                await update.message.reply_text(
                    f"❌ Không tìm thấy kênh.\nLỗi: `{str(e)[:80]}`",
                    parse_mode="Markdown",
                    reply_markup=back_only_kb()
                )
            return

    await update.message.reply_text("❓ Dùng menu 👇", reply_markup=main_menu(role))


# ============================================
# CALLBACK
# ============================================
async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user = get_user(q.from_user.id)
    if not user or user["admin_role"] != "super":
        await q.edit_message_text("⛔ Chỉ Admin Chính.")
        return

    data = q.data

    if data.startswith("apk_"):
        req_id = int(data.split("_")[1])
        req = get_key_req(req_id)
        if not req:
            return
        approve_key(req_id, user["admin_user"])
        info = KEY_TYPES.get(req["key_type"], {})
        dur = DURATIONS.get(req["duration"], {})
        await q.edit_message_text(
            f"✅ *ĐÃ DUYỆT KEY*\n"
            f"🏷 Loại: *{info.get('name', '?')}*\n"
            f"⏱ Thời hạn: *{dur.get('name', '?')}*\n"
            f"🔑 `{req['key_value']}`\n"
            f"👤 Admin phụ: `{req['admin_user']}`",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                req["tg_id"],
                f"✅ *KEY CỦA BẠN ĐÃ ĐƯỢC DUYỆT*\n"
                f"🏷 Loại: *{info.get('name', '?')}*\n"
                f"⏱ Thời hạn: *{dur.get('name', '?')}*\n"
                f"🔑 `{req['key_value']}`\n"
                f"🗑 Tự xoá sau 40s",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif data.startswith("rjk_"):
        req_id = int(data.split("_")[1])
        req = get_key_req(req_id)
        reject_key(req_id, user["admin_user"])
        await q.edit_message_text(f"❌ Đã từ chối `{req['key_value']}`", parse_mode="Markdown")

    elif data.startswith("apb_"):
        bill_id = int(data.split("_")[1])
        approve_bill(bill_id, user["admin_user"])
        await q.edit_message_text(f"✅ Đã duyệt bill #{bill_id}")


# ============================================
# FLASK
# ============================================
flask_app = Flask(__name__)


@flask_app.route("/")
@flask_app.route("/health")
def health():
    return "OK", 200


# ============================================
# BOT
# ============================================
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Bắt đầu"),
        BotCommand("login", "Đăng nhập"),
        BotCommand("logout", "Đăng xuất"),
        BotCommand("help", "Trợ giúp"),
    ])
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def build_application():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    return app


def run_bot_webhook():
    init_db()
    application = build_application()

    webhook_path = f"/webhook/{BOT_TOKEN}"
    full_url = f"{RENDER_URL}{webhook_path}" if RENDER_URL else None

    logger.info(f"🤖 Khởi động bot | RENDER_URL={RENDER_URL}")

    async def _start():
        if full_url:
            await application.bot.set_webhook(url=full_url)
            logger.info(f"✅ Webhook set: {full_url}")
        await application.initialize()
        await application.start()
        await application.updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_url,
        )
        logger.info(f"✅ Bot listening on port {PORT}")
        await asyncio.Event().wait()

    asyncio.run(_start())


def self_ping():
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        logger.info("⚠️ Không có RENDER_EXTERNAL_URL — bỏ qua self-ping")
        return
    time.sleep(60)
    while True:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=10)
        except Exception:
            pass
        time.sleep(14 * 60)


if __name__ == "__main__":
    threading.Thread(target=run_bot_webhook, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    logger.info(f"🌐 Flask listening on 0.0.0.0:{PORT}")
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)