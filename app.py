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
        logger.info(f"✅ Kullanıcı {user_id} sorgu hakkı güncellendi: {new_count}")
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
            
            logger.info(f"📨 Davet ekleniyor: {user_id} -> {current_invites} -> {new_invites}")
            
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
                logger.info(f"🎉 Kullanıcı {user_id} 30 sorgu hakkı bonusu kazandı! Yeni hak: {new_searches}")
                return True
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Kullanıcı {user_id} davet sayısı güncellendi: {new_invites}")
        
        return False
        
    except Exception as e:
        logger.error(f"❌ add_invite hatası: {e}")
        return False

# Google Drive'dan JSON indirme - GÜNCELLENMİŞ
def download_json_file():
    json_path = "sicil.json"
    
    # Önce mevcut dosyayı sil (cache problemi)
    if os.path.exists(json_path):
        os.remove(json_path)
        logger.info("🗑️ Eski JSON dosyası silindi")
    
    try:
        # DIRECT Google Drive link
        drive_url = "https://drive.google.com/uc?id=1dIkedxpzP7GSPDPbkGAise-WhZ3oTwJ0"
        logger.info(f"📥 DIRECT Drive indirme: {drive_url}")
        
        # gdown ile indir
        gdown.download(drive_url, json_path, quiet=False)
        
        # Kontrol et
        if os.path.exists(json_path):
            file_size = os.path.getsize(json_path)
            logger.info(f"✅ JSON indirildi! Boyut: {file_size} bytes")
            
            if file_size > 0:
                return True
            else:
                logger.error("❌ Dosya boş!")
                return False
        else:
            logger.error("❌ Dosya oluşturulamadı!")
            return False
            
    except Exception as e:
        logger.error(f"🚨 İndirme hatası: {str(e)}")
        logger.error(f"🚨 Traceback: {traceback.format_exc()}")
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
    json_loaded = os.path.exists('sicil.json')
    return jsonify({
        "status": "active", 
        "message": "Sicil Sorgulama Bot API",
        "json_loaded": json_loaded
    })

@app.route('/health')
def health():
    json_status = download_json_file()  # Zorunlu indirme
    file_size = os.path.getsize('sicil.json') if json_status else 0
    
    return jsonify({
        "status": "healthy" if json_status else "error",
        "json_downloaded": json_status,
        "json_size": file_size,
        "drive_url": "https://drive.google.com/uc?id=1dIkedxpzP7GSPDPbkGAise-WhZ3oTwJ0"
    })

@app.route('/test-drive')
def test_drive():
    """Google Drive bağlantı testi"""
    try:
        test_url = "https://drive.google.com/uc?id=1dIkedxpzP7GSPDPbkGAise-WhZ3oTwJ0"
        response = requests.get(test_url, stream=True)
        
        return jsonify({
            "status_code": response.status_code,
            "content_type": response.headers.get('content-type', ''),
            "content_length": response.headers.get('content-length', '0')
        })
    except Exception as e:
        return jsonify({"error": str(e)})

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
            
            # Referans işlemi
            if context.args:
                try:
                    referrer_id = int(context.args[0])
                    if referrer_id != user_id:
                        bonus_verildi = add_invite(referrer_id)
                        if bonus_verildi:
                            await context.bot.send_message(
                                referrer_id,
                                "🎉 **TEBRİKLER! 3 KİŞİ DAVET ETTİNİZ!**\n\n"
                                "✅ **30 SORGU HAKKI** kazandınız!\n\n"
                                "@nabisystem @watronschecker"
                            )
                except ValueError:
                    pass
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            
            if missing_channels:
                buttons = []
                for channel in missing_channels:
                    buttons.append([InlineKeyboardButton(f"📢 {channel} Katıl", url=f"https://t.me/{channel[1:]}")])
                buttons.append([InlineKeyboardButton("✅ Kontrol Et", callback_data="check_membership")])
                reply_markup = InlineKeyboardMarkup(buttons)
                
                await update.message.reply_text(
                    "❌ **Kanal Üyeliği Gerekli**\n\n"
                    "Botu kullanmak için aşağıdaki kanallara katılmanız gerekiyor:\n\n" +
                    "\n".join([f"• {channel}" for channel in missing_channels]) +
                    "\n\nKanallara katıldıktan sonra '✅ Kontrol Et' butonuna tıklayın.",
                    reply_markup=reply_markup
                )
                return
            
            # Ana menü
            user_data = get_user_data(user_id)
            await update.message.reply_text(
                f"🔍 **Sicil Sorgulama Botu**\n\n"
                f"**Kalan Sorgu Hakkı:** {user_data['remaining_searches']}\n"
                f"**Davet Edilen:** {user_data['invited_users']}/3 kişi\n"
                f"**Toplam Davet:** {user_data['total_invites']} kişi\n"
                f"**Bonus Durumu:** {'✅ 30 HAK KAZANILDI' if user_data['bonus_received'] else '❌ 30 HAK BEKLİYOR'}\n\n"
                "**Komutlar:**\n"
                "• `/sicil 12345678901` - TC sorgula\n"
                "• `/referans` - Davet linkini al\n\n"
                "🎉 **3 arkadaşını davet et, 30 SORGU HAKKI kazan!**\n\n"
                "@nabisystem @watronschecker"
            )

        async def sicil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            if missing_channels:
                await update.message.reply_text("❌ Önce tüm kanallara katılmalısınız! /start")
                return
            
            user_data = get_user_data(user_id)
            
            if user_data['remaining_searches'] <= 0:
                await update.message.reply_text(
                    "❌ **Sorgu hakkınız kalmadı!**\n\n"
                    "Yeni hak kazanmak için 3 arkadaşınızı davet edin:\n"
                    "`/referans`\n\n"
                    "🎉 **3 davet = 30 SORGU HAKKI!**\n\n"
                    "@nabisystem @watronschecker"
                )
                return
            
            if not context.args:
                await update.message.reply_text("❌ **Doğru kullanım:** `/sicil 12345678901`")
                return
            
            tc = context.args[0]
            
            if not tc.isdigit() or len(tc) != 11:
                await update.message.reply_text("❌ Geçersiz TC kimlik numarası! 11 haneli numara girin.")
                return
            
            # Hak sayısını güncelle
            update_user_searches(user_id, user_data['remaining_searches'] - 1)
            
            await update.message.reply_text("🔍 Sicil kayıtları aranıyor... @nabisystem @watronschecker")
            
            # Arama yap
            sonuclar = search_by_tc(tc)
            
            if isinstance(sonuclar, str):
                await update.message.reply_text(f"❌ {sonuclar}\n\n@nabisystem @watronschecker")
                return
            
            if not sonuclar:
                await update.message.reply_text(f"❌ **{tc}** numarasına ait sicil kaydı bulunamadı.\n\n@nabisystem @watronschecker")
                return
            
            # Sonuçları göster (ilk 3 kayıt)
            for i, kayit in enumerate(sonuclar[:3]):
                mesaj = f"**Kayıt {i+1}:**\n"
                
                if kayit.get('KISI_TC_KIMLIK_NO') == tc:
                    mesaj += f"👤 **Müvekkil:** {kayit.get('KISI_ADI', '')} {kayit.get('KISI_SOYAD', '')}\n"
                    mesaj += f"⚖️ **Suç:** {kayit.get('KISI_SUC_ADI', '')}\n"
                    mesaj += f"🎭 **Tip:** {kayit.get('KISI_TIP_ADI', '')}\n"
                else:
                    mesaj += f"⚖️ **Avukat:** {kayit.get('AVUKAT_ADI', '')} {kayit.get('AVUKAT_SOYADI', '')}\n"
                    mesaj += f"🔢 **Sicil No:** {kayit.get('AVUKAT_SICIL_NO', '')}\n"
                
                mesaj += f"📁 **Dosya:** {kayit.get('DOSYA_NO', '')}\n"
                mesaj += f"🏛️ **Kurum:** {kayit.get('KURUM_ADI', '')}\n"
                mesaj += f"📅 **Tarih:** {kayit.get('GOREV_TARIHI', '')[:10]}\n\n"
                mesaj += "@nabisystem @watronschecker"
                
                await update.message.reply_text(mesaj)
            
            # Kalan hakları göster
            user_data = get_user_data(user_id)
            await update.message.reply_text(
                f"✅ **Arama tamamlandı!**\n"
                f"**Kalan Sorgu Hakkı:** {user_data['remaining_searches']}\n"
                f"**Bulunan Kayıt:** {len(sonuclar)} adet\n\n"
                "@nabisystem @watronschecker"
            )

        async def referans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            # Kanal kontrolü
            missing_channels = await check_channel_membership(update, context)
            if missing_channels:
                await update.message.reply_text("❌ Önce tüm kanallara katılmalısınız! /start")
                return
            
            user_data = get_user_data(user_id)
            
            bot_username = (await context.bot.get_me()).username
            invite_link = f"https://t.me/{bot_username}?start={user_id}"
            
            # Davet durumuna göre mesaj
            if user_data['bonus_received']:
                bonus_text = "✅ **30 SORGU HAKKI ZATEN KAZANILDI!**"
                info_text = "🎉 Bonusu zaten aldınız! Yeni davetler için teşekkürler."
            elif user_data['invited_users'] >= 3:
                bonus_text = "✅ **30 SORGU HAKKI HAK EDİLDİ!**"
                info_text = "🎉 3 kişi davet ettiniz! Bonus otomatik olarak eklendi."
            else:
                kalan = 3 - user_data['invited_users']
                bonus_text = f"❌ **{kalan} kişi kaldı!**"
                info_text = f"🔥 {kalan} kişi daha davet ederek 30 SORGU HAKKI kazan!"
            
            await update.message.reply_text(
                f"📨 **REFERANS SİSTEMİ**\n\n"
                f"**Davet Durumu:** {user_data['invited_users']}/3 kişi\n"
                f"**Toplam Davet:** {user_data['total_invites']} kişi\n"
                f"**Bonus:** {bonus_text}\n\n"
                f"{info_text}\n\n"
                f"**Davet Linkiniz:**\n`{invite_link}`\n\n"
                "📍 **Nasıl Çalışır?**\n"
                "1. Linki arkadaşlarınıza gönderin\n"
                "2. Onlar botu kullanmaya başlasın\n"
                "3. 3 kişi tamamlayınca 30 HAK kazanın!\n\n"
                "@nabisystem @watronschecker"
            )

        async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            
            missing_channels = await check_channel_membership(update, context)
            
            if not missing_channels:
                await query.edit_message_text("✅ **Tüm kanallara katılım onaylandı!**\n\nBotu kullanmaya başlayabilirsiniz.")
                await start_command(update, context)
            else:
                await query.edit_message_text("❌ **Hala kanallara katılmadınız!** Lütfen /start komutu ile tekrar deneyin.")

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
