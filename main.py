import time
import requests
import threading
import os
from datetime import datetime
import pytz
from flask import Flask
from playwright.sync_api import sync_playwright

# ================= CONFIGURACIÓN =================
URL_LOGIN = "https://eventossistema.com.mx/login.html"
URL_EVENTS = "https://eventossistema.com.mx/confirmaciones/default.html"
CHECK_INTERVAL = 90 
NO_EVENTS_TEXT = "No hay eventos disponibles por el momento."
TZ = pytz.timezone("America/Mexico_City")

USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

app = Flask(__name__)

@app.route("/")
def home():
    return f"Bot Madian Híbrido Activo - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        logged = False

        while True:
            try:
                if not logged:
                    page.goto(URL_LOGIN)
                    page.wait_for_timeout(3000)
                    page.keyboard.press("Tab"); page.keyboard.type(USER, delay=100)
                    page.keyboard.press("Tab"); page.keyboard.type(PASS, delay=100)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(10000)
                    logged = True

                page.goto(URL_EVENTS, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)
                content = page.inner_text("body")

                # 1. VERIFICACIÓN CRÍTICA (Como el bot original)
                if NO_EVENTS_TEXT not in content and "EVENTOS DISPONIBLES" in content:
                    # PRIMER AVISO: ¡Algo cambió! (Aviso instantáneo)
                    send(f"🚨 *MADIAN: ¡EVENTOS DETECTADOS!* 🚨\nRevisa de inmediato, el sistema muestra cambios.")
                    
                    # 2. INTENTO DE ANÁLISIS (Si falla, no importa, ya te avisó arriba)
                    try:
                        # Extraemos un resumen rápido de lo que se ve en pantalla sin hacer clics
                        resumen = content.split("EVENTOS DISPONIBLES")[-1].split("EVENTOS CONFIRMADOS")[0].strip()
                        if len(resumen) > 10:
                            send(f"📝 *Detalle rápido:* \n`{resumen[:500]}`")
                    except:
                        send("⚠️ No pude extraer el detalle, pero hay eventos en la lista.")

                else:
                    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Madian: Todo tranquilo.")

            except Exception as e:
                print(f"Error: {e}")
                logged = False
                time.sleep(30)
            
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
    
