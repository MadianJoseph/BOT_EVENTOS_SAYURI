import time
import requests
import threading
import os
import re
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

LUGARES_OK = ["PALACIO DE LOS DEPORTES", "ESTADIO GNP", "AUTODROMO HERMANOS RODRIGUEZ", "ESTADIO ALFREDO HARP HELU", "DIABLOS"]
PUESTOS_NO = ["ACREDITACIONES", "ANFITRION", "MKT", "OVG", "FAN ID"]

app = Flask(__name__)

@app.route("/")
def home(): return f"Bot Sayuri (Filtro Silencioso) Activo - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                       data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"titulo": "", "puesto": "", "inicio": "", "lugar": "", "turnos": "0"}
    lugar_match = re.search(r'LUGAR</td><td.*?>(.*?)</td>', html_content)
    if lugar_match: info['lugar'] = lugar_match.group(1).strip()
    horario_match = re.search(r'HORARIO</td><td.*?>(.*?)</td>', html_content, re.DOTALL)
    if horario_match:
        texto_h = horario_match.group(1)
        fecha_m = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2})', texto_h)
        if fecha_m: info['inicio'] = fecha_m.group(1)
        turnos_m = re.search(r'TURNOS\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
        if turnos_m: info['turnos'] = turnos_m.group(1)
    return info

def analizar_sayuri(info, titulo_card, es_bloque):
    titulo = titulo_card.upper()
    lugar = info['lugar'].upper()
    try:
        inicio_dt = TZ.localize(datetime.strptime(info['inicio'], "%d/%m/%Y %H:%M"))
    except: return False, "Fecha no legible"

    if es_bloque: return False, "Es BLOQUE"
    if not any(l in lugar for l in LUGARES_OK): return False, f"Lugar: {lugar}"
    if "TRASLADO" in titulo or "GIRA" in titulo: return False, "Es TRASLADO/GIRA"
    if any(p in titulo for p in PUESTOS_NO): return False, "Puesto prohibido"
    if inicio_dt.hour >= 17: return False, "Horario nocturno"
    return True, "OK"

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
                    page.keyboard.press("Tab"); page.keyboard.type(USER)
                    page.keyboard.press("Tab"); page.keyboard.type(PASS); page.keyboard.press("Enter")
                    page.wait_for_timeout(8000); logged = True

                page.goto(URL_EVENTS, wait_until="networkidle")
                if NO_EVENTS_TEXT not in page.content():
                    cards = page.query_selector_all(".card.border")
                    for card in cards:
                        # FILTRO CRÍTICO: Solo procesar si tiene botón CONFIRMAR
                        btn_confirmar = card.query_selector("button:has-text('CONFIRMAR')")
                        if not btn_confirmar: continue 

                        titulo_elem = card.query_selector("h6 a")
                        if not titulo_elem: continue
                        titulo_texto = titulo_elem.inner_text()
                        es_bloque = "BLOQUE" in card.inner_text().upper()

                        titulo_elem.click(); page.wait_for_timeout(2000)
                        tabla_elem = card.query_selector(".table-responsive")
                        if not tabla_elem: continue
                        info = extraer_datos_tabla(tabla_elem.inner_html())
                        
                        apto, motivo = analizar_sayuri(info, titulo_texto, es_bloque)
                        if apto:
                            btn_confirmar.click(); page.wait_for_timeout(2000)
                            send(f"✅ *SAYURI: CONFIRMADO*\n📌 {titulo_texto}\n📍 {info['lugar']}\n⏰ {info['inicio']}")
                        else:
                            send(f"📋 *SAYURI (AVISO):* {titulo_texto}\n❌ Motivo: {motivo}\n⏰ {info['inicio']}")
                else:
                    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] Sayuri: Sin eventos.")
            except: logged = False; time.sleep(30)
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=bot_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
