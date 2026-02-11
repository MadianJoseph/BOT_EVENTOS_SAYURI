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

# Credenciales de Sayuri (Configura estas en su propio Render)
USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LUGARES_OK = ["PALACIO DE LOS DEPORTES", "ESTADIO GNP", "AUTODROMO HERMANOS RODRIGUEZ", "ESTADIO ALFREDO HARP HELU", "DIABLOS"]

app = Flask(__name__)

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def analizar_sayuri(info):
    """Filtros específicos para la cuenta de Sayuri"""
    titulo = info['titulo'].upper()
    lugar = info['lugar'].upper()
    is_bloque = info['is_bloque']
    
    try:
        inicio_dt = TZ.localize(datetime.strptime(info['inicio'], "%d/%m/%Y %H:%M"))
    except: return False, "Error de fecha"

    # 1. Regla de BLOQUE (Nunca confirmar, solo avisar)
    if is_bloque: return False, "Evento marcado como BLOQUE (Revisar manualmente)"

    # 2. Lugar y Traslados
    if not any(l in lugar for l in LUGARES_OK): return False, f"Lugar: {lugar}"
    if "TRASLADO" in titulo or "GIRA" in titulo: return False, "Es TRASLADO o GIRA"

    # 3. Sayuri NO tiene límite de turnos (Acepta 1, 1.5, 2, 2.5)
    # Solo revisamos que no sea un horario nocturno prohibido
    if inicio_dt.hour >= 17: return False, "Horario nocturno (Entrada tarde)"

    # 4. Domingo (No antes de las 9:30 AM)
    if inicio_dt.weekday() == 6: 
        if inicio_dt.hour < 9 or (inicio_dt.hour == 9 and inicio_dt.minute < 30):
            return False, "Domingo temprano (Antes 9:30 AM)"

    return True, "Filtros OK"

def bot_worker():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
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

                if "ID USUARIO" in content.upper():
                    logged = False; continue

                # DETECCIÓN DE EVENTOS
                if NO_EVENTS_TEXT not in content:
                    # Buscamos los contenedores de eventos (ajustar selector si es necesario)
                    eventos_visibles = page.query_selector_all(".row-evento, .card-evento, [onclick*='confirmar']")
                    
                    for ev in eventos_visibles:
                        # Revisamos si tiene el texto BLOQUE antes de abrirlo
                        es_bloque = "BLOQUE" in ev.inner_text().upper()
                        
                        ev.click() # Abrimos el detalle
                        page.wait_for_timeout(3000)
                        
                        # Extraemos info real del modal/detalle (Simulado aquí)
                        # Nota: En la vida real, aquí usaríamos page.inner_text("#ID-DEL-DETALLE")
                        info = {
                            "titulo": "SAYURI - EVENTO DETECTADO",
                            "lugar": "Estadio GNP",
                            "inicio": "14/02/2026 13:30",
                            "turnos": "2.0",
                            "is_bloque": es_bloque
                        }

                        apto, motivo = analizar_sayuri(info)

                        if apto:
                            # page.click("#boton-confirmar") # Selector de confirmación real
                            send(f"✅ *SAYURI: EVENTO CONFIRMADO*\n📌 {info['titulo']}\n⏰ {info['inicio']}\n📊 Turnos: {info['turnos']}")
                        else:
                            send(f"📋 *SAYURI: AVISO*\nEvento: {info['titulo']}\nMotivo: {motivo}\n⏰ {info['inicio']}")
                
                else:
                    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sayuri: Sin eventos.")

            except Exception as e:
                print(f"Error Sayuri: {e}")
                logged = False
                time.sleep(30)

            time.sleep(CHECK_INTERVAL)

@app.route("/")
def home(): return "Bot Sayuri Online"

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
                      
