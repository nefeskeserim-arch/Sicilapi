import os
import json
import gdown
import requests
from flask import Flask, jsonify
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import threading
import logging
import sqlite3
import traceback

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Zorunlu kanallar
REQUIRED_CHANNELS = ["@nabisystem", "@watronschecker"]

# Database için
def init_db():
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                remaining_searches INTEGER DEFAULT 3,
                invited_users INTEGER DEFAULT 0,
                total_invites INTEGER DEFAULT 0,
                bonus_received BOOLEAN DEFAULT FALSE
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("✅ Database tablosu oluşturuldu")
    except Exception as e:
        logger.error(f"❌ Database hatası: {e}")

def get_user_data(user_id):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.execute('''
                INSERT INTO users (user_id, remaining_searches, invited_users, total_invites, bonus_received) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, 3, 0, 0, False))
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user = cursor.fetchone()
        
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'remaining_searches': user[1],
                'invited_users': user[2],
                'total_invites': user[3],
                'bonus_received': bool(user[4])
            }
        else:
            return {
                'user_id': user_id,
                'remaining_searches': 3,
                'invited_users': 0,
                'total_invites': 0,
                'bonus_received': False
            }
            
    except Exception as e:
        logger.error(f"❌ get_user_data hatası: {e}")
        return {
            'user_id': user_id,
            'remaining_searches': 3,
            'invited_users': 0,
            'total_invites': 0,
            'bonus_received': False
        }

def update_user_searches(user_id, new_count):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET remaining_searches = ? WHERE user_id = ?', (new_count, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ update_user_searches hatası: {e}")

def add_invite(user_id):
    try:
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT invited_users, bonus_received FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        
        if result:
            current_invites = result[0]
            bonus_received = bool(result[1])
            new_invites = current_invites + 1
            
            cursor.execute('UPDATE users SET invited_users = ?, total_invites = total_invites + 1 WHERE user_id = ?', 
                          (new_invites, user_id))
            
            if new_invites >= 3 and not bonus_received:
                cursor.execute('SELECT remaining_searches FROM users WHERE user_id = ?', (user_id,))
                current_searches = cursor.fetchone()[0]
                new_searches = current_searches + 30
                
                cursor.execute('UPDATE users SET remaining_searches = ?, bonus_received = TRUE WHERE user_id = ?', 
                              (new_searches, user_id))
                conn.commit()
                conn.close()
                return True
            
            conn.commit()
            conn.close()
        
        return False
        
    except Exception as e:
        logger.error(f"❌ add_invite hatası: {e}")
        return False

# Google Drive'dan JSON indirme
def get_drive_link_from_github():
    try:
        github_raw_url = "https://raw.githubusercontent.com/KULLANICI_ADI/REPO_ADI/main/drive_link.txt"
        response = requests.get(github_raw_url)
        if response.status_code == 200:
            return response.text.strip()
        else:
            # Fallback: direkt link
            return "https://drive.google.com/uc?id=1dIkedxpzP7GSPDPbkGAise-WhZ3oTwJ0"
    except Exception as e:
        logger.error(f"GitHub bağlantı hatası: {e}")
        return "https://drive.google.com/uc?id=1dIkedxpzP7GSPDPbkGAise-WhZ3oTwJ0"

def download_json_file():
    json_path = "sicil.json"
    
    # Eğer dosya varsa ve 1 saatten eski değilse yeniden indirme
    if os.path.exists(json_path):
        file_time = os.path.getmtime(json_path)
        current_time = os.path.getmtime(__file__)  # Bu dosyanın zamanı
        if (current_time - file_time) < 3600:  # 1 saat
            logger.info("✅ JSON dosyası zaten güncel")
            return True
    
    try:
        drive_url = get_drive_link_from_github()
        logger.info(f"📥 Drive'dan indiriliyor: {drive_url}")
        
        gdown.download(drive_url, json_path, quiet=False)
        
        if os.path.exists(json_path) and os.path.getsize(json_path) > 0:
            logger.info("✅ JSON dosyası başarıyla indirildi")
            return True
        else:
            logger.error("❌ İndirilen dosya boş veya hatalı")
            return False
            
    except Exception as e:
        logger.error(f"❌ İndirme hatası: {e}")
        return False

def search_by_tc(tc):
    try:
        if not download_json_file():
            return "JSON dosyası yüklenemedi"
        
        with open('sicil.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        sonuclar = []
        toplam_sayfa = 0
        toplam_kayit = 0
        
        if isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    if 'Veri' in item and isinstance(item['Veri'], list):
                        toplam_sayfa += 1
                        sayfa_kayitlari = item['Veri']
                        toplam_kayit += len(sayfa_kayitlari)
                        
                        for kayit in sayfa_kayitlari:
                            if isinstance(kayit, dict):
                                kisi_tc = str(kayit.get('KISI_TC_KIMLIK_NO', '')).strip()
                                avukat_tc = str(kayit.get('AVUKAT_TC_KIMLIK_NO', '')).strip()
                                
                                if kisi_tc == tc or avukat_tc == tc:
                                    sonuclar.append(kayit)
                    
                    elif any(key in item for key in ['KISI_TC_KIMLIK_NO', 'AVUKAT_TC_KIMLIK_NO']):
                        toplam_kayit += 1
                        kisi_tc = str(item.get('KISI_TC_KIMLIK_NO', '')).strip()
                        avukat_tc = str(item.get('AVUKAT_TC_KIMLIK_NO', '')).strip()
                        
                        if kisi_tc == tc or avukat_tc == tc:
                            sonuclar.append(item)
        
        logger.info(f"✅ {toplam_sayfa} sayfa, {toplam_kayit} kayıt tarandı, {len(sonuclar)} eşleşme")
        return sonuclar
        
    except Exception as e:
        return f"Hata: {e}"

# Flask routes
@app.route('/')
def home():
    return jsonify({
        "status": "active", 
        "message": "Sicil Sorgulama Bot API",
        "json_loaded": os.path.exists('sicil.json')
    })

@app.route('/health')
def health():
    json_status = download_json_file()
    return jsonify({
        "status": "healthy",
        "json_downloaded": json_status,
        "json_size": os.path.getsize('sicil.json') if json_status else 0
    })

# Telegram Bot
def run_telegram_bot():
    try:
        BOT_TOKEN = os.getenv('BOT_TOKEN', '8259938188:AAFy5l5UWmGThqFNwDu2gyqybOh_hE3vPfM')
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            missing_channels = []
            
            for channel in REQUIRED_CHANNELS:
                try:
                    member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                    if member.status not in ['member', 'administrator', 'creator']:
                        missing_channels.append(channel)
                except Exception as e:
                    missing_channels.append(channel)
            
            return missing_channels

        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            if context.args:
                try:
                    referrer_id = int(context.args[0])
                    if referrer_id != user_id:
                        add_invite(referrer_id)
                except ValueError:
                    pass
            
            missing_channels = await check_channel_membership(update, context)
            
            if missing_channels:
                buttons = []
                for channel in missing_channels:
                    buttons.append([InlineKeyboardButton(f"📢 {channel} Katıl", url=f"https://t.me/{channel[1:]}")])
                buttons.append([InlineKeyboardButton("✅ Kontrol Et", callback_data="check_membership")])
                reply_markup = InlineKeyboardMarkup(buttons)
                
                await update.message.reply_text(
                    "❌ Kanallara katılın!",
                    reply_markup=reply_markup
                )
                return
            
            user_data = get_user_data(user_id)
            await update.message.reply_text(
                f"🔍 **Sicil Sorgulama Botu**\n\n"
                f"**Kalan Hak:** {user_data['remaining_searches']}\n"
                f"**Davet:** {user_data['invited_users']}/3\n"
                f"**Bonus:** {'✅ Alındı' if user_data['bonus_received'] else '❌ Bekliyor'}\n\n"
                "**Komutlar:**\n• `/sicil 12345678901`\n• `/referans`\n\n"
                "🎉 **3 davet = 30 SORGU HAKKI!**"
            )

        async def sicil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            missing_channels = await check_channel_membership(update, context)
            if missing_channels:
                await update.message.reply_text("❌ Önce kanallara katılın! /start")
                return
            
            user_data = get_user_data(user_id)
            
            if user_data['remaining_searches'] <= 0:
                await update.message.reply_text("❌ Hak kalmadı! /referans")
                return
            
            if not context.args:
                await update.message.reply_text("❌ Kullanım: /sicil 12345678901")
                return
            
            tc = context.args[0]
            if not tc.isdigit() or len(tc) != 11:
                await update.message.reply_text("❌ Geçersiz TC!")
                return
            
            update_user_searches(user_id, user_data['remaining_searches'] - 1)
            await update.message.reply_text("🔍 Aranıyor...")
            
            sonuclar = search_by_tc(tc)
            
            if isinstance(sonuclar, str):
                await update.message.reply_text(f"❌ {sonuclar}")
                return
            
            if not sonuclar:
                await update.message.reply_text(f"❌ {tc} bulunamadı")
                return
            
            for i, kayit in enumerate(sonuclar[:3]):
                mesaj = f"**Kayıt {i+1}:**\n"
                
                if kayit.get('KISI_TC_KIMLIK_NO') == tc:
                    mesaj += f"👤 **Müvekkil:** {kayit.get('KISI_ADI', '')} {kayit.get('KISI_SOYAD', '')}\n"
                    mesaj += f"⚖️ **Suç:** {kayit.get('KISI_SUC_ADI', '')}\n"
                else:
                    mesaj += f"⚖️ **Avukat:** {kayit.get('AVUKAT_ADI', '')} {kayit.get('AVUKAT_SOYADI', '')}\n"
                
                mesaj += f"📁 **Dosya:** {kayit.get('DOSYA_NO', '')}\n"
                mesaj += f"🏛️ **Kurum:** {kayit.get('KURUM_ADI', '')}\n"
                await update.message.reply_text(mesaj)
            
            user_data = get_user_data(user_id)
            await update.message.reply_text(f"✅ Tamamlandı! Kalan Hak: {user_data['remaining_searches']}")

        async def referans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            user_data = get_user_data(user_id)
            
            bot_username = (await context.bot.get_me()).username
            invite_link = f"https://t.me/{bot_username}?start={user_id}"
            
            await update.message.reply_text(
                f"📨 **Referans Sistemi**\n\n"
                f"**Davet:** {user_data['invited_users']}/3 kişi\n"
                f"**Bonus:** {'✅ 30 HAK ALINDI' if user_data['bonus_received'] else '❌ 30 HAK BEKLİYOR'}\n\n"
                f"**Link:** `{invite_link}`\n\n"
                "🔥 **3 kişi davet et, 30 HAK kazan!**"
            )

        async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            
            missing_channels = await check_channel_membership(update, context)
            
            if not missing_channels:
                await query.edit_message_text("✅ Kanallara katılım onaylandı!")
                await start_command(update, context)
            else:
                await query.edit_message_text("❌ Hala katılmadınız! /start")

        # Handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("sicil", sicil_command))
        application.add_handler(CommandHandler("referans", referans_command))
        application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="check_membership"))
        
        logger.info("🤖 Telegram bot başlatılıyor...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"❌ Bot hatası: {e}")

# Uygulamayı başlat
if __name__ == '__main__':
    # Database'i başlat
    init_db()
    
    # JSON'u önceden indir
    logger.info("📥 JSON dosyası indiriliyor...")
    download_json_file()
    
    # Bot'u thread'te başlat
    bot_thread = threading.Thread(target=run_telegram_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Flask'ı başlat
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🌐 Flask API başlatılıyor: port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
