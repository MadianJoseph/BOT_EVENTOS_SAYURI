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

# Credenciales de Sayuri
USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LUGARES_OK = ["PALACIO DE LOS DEPORTES", "ESTADIO GNP", "AUTODROMO HERMANOS RODRIGUEZ", "ESTADIO ALFREDO HARP HELU", "DIABLOS"]

app = Flask(__name__)

@app.route("/")
def home():
    return f"Bot Sayuri 24/7 Activo - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def analizar_sayuri(info):
    titulo = info['titulo'].upper()
    lugar = info['lugar'].upper()
    is_bloque = info['is_bloque']
    try:
        inicio_dt = TZ.localize(datetime.strptime(info['inicio'], "%d/%m/%Y %H:%M"))
    except: return False, "Error fecha"

    if is_bloque: return False, "Evento BLOQUE (Revisión manual)"
    if not any(l in lugar for l in LUGARES_OK): return False, "Lugar no permitido"
    if "TRASLADO" in titulo or "GIRA" in titulo: return False, "Traslado/Gira"
    
    # Sayuri acepta cualquier turnaje (1, 1.5, 2, 2.5)
    # Filtro de horario nocturno
    if inicio_dt.hour >= 17: return False, "Nocturna (Entrada tarde)"
    
    # Domingo temprano
    if inicio_dt.weekday() == 6 and (inicio_dt.hour < 9 or (inicio_dt.hour == 9 and inicio_dt.minute < 30)):
        return False, "Domingo mañana"

    return True, "Filtros OK"

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0...")
        page = context.new_page()
        logged = False

        while True:
            try:
                # SE ELIMINÓ LA RESTRICCIÓN DE IF (6 <= now.hour < 24)
                # Ahora el bot siempre intentará entrar.

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

                if "ID USUARIO" in content.upper():
                    logged = False; continue

                if NO_EVENTS_TEXT not in content:
                    eventos_visibles = page.query_selector_all(".row-evento, .card-evento")
                    for ev in eventos_visibles:
                        es_bloque = "BLOQUE" in ev.inner_text().upper()
                        ev.click()
                        page.wait_for_timeout(3000)
                        
                        # Simulación de extracción
                        info = {"titulo": "SAYURI 24/7", "lugar": "ESTADIO GNP", "inicio": "20/02/2026 13:30", "turnos": "2.0", "is_bloque": es_bloque}
                        
                        apto, motivo = analizar_sayuri(info)
                        if apto:
                            # page.click("#confirmar")
                            send(f"✅ SAYURI (24/7): CONFIRMADO {info['titulo']}")
                        else:
                            send(f"📋 SAYURI (24/7): {info['titulo']} - {motivo}")
                else:
                    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sayuri Vigilando...")

            except Exception as e:
                print(f"Error Sayuri: {e}")
                logged = False
                time.sleep(30)
            
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    t = threading.Thread(target=bot_worker, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    
