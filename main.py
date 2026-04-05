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
CHECK_INTERVAL = 60 
TZ = pytz.timezone("America/Mexico_City")

USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Memoria para limitar mensajes de estadios (Máximo 5 avisos por evento)
HISTORIAL_ESTADIOS = {} 
ESTADIOS_LIMITADOS = ["ESTADIO AZTECA", "ESTADIO CIUDAD DE LOS DEPORTES", "AZTECA"]

app = Flask(__name__)

@app.route("/")
def home(): 
    return f"Bot Asistente Jimena V4.3 - Online - {datetime.now(TZ).strftime('%H:%M:%S')}"

def send(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try: 
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos_tabla(html_content):
    info = {"puesto": "", "turnos": "0", "lugar": "", "indicaciones": "", "mins_entrada": 0, "fecha_dt": None}
    try:
        p_match = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html_content)
        if p_match: info['puesto'] = p_match.group(1).strip().upper()
        
        l_match = re.search(r'LUGAR</td><td.*?>(.*?)</td>', html_content)
        if l_match: info['lugar'] = l_match.group(1).strip().upper()

        i_match = re.search(r'INDICACIONES</td><td.*?>(.*?)</td>', html_content)
        if i_match: info['indicaciones'] = i_match.group(1).strip().upper()
        
        h_match = re.search(r'HORARIO</td><td.*?>(.*?)</td>', html_content, re.DOTALL)
        if h_match:
            texto_h = h_match.group(1)
            t_match = re.search(r'TURNOS\s*(\d+\.?\d*)', texto_h, re.IGNORECASE)
            if t_match: info['turnos'] = t_match.group(1)
            
            hora_m = re.search(r'(\d{2}):(\d{2})', texto_h)
            if hora_m:
                h, m = int(hora_m.group(1)), int(hora_m.group(2))
                info['mins_entrada'] = (h * 60) + m
            
            f_match = re.search(r'(\d{2}/\d{2}/\d{2,4})', texto_h)
            if f_match and hora_m:
                fecha_str = f"{f_match.group(1)} {hora_m.group(1)}:{hora_m.group(2)}"
                fmt = "%d/%m/%y %H:%M" if len(f_match.group(1).split('/')[-1]) == 2 else "%d/%m/%Y %H:%M"
                info['fecha_dt'] = TZ.localize(datetime.strptime(fecha_str, fmt))
    except: pass
    return info

def analizar_filtros(info, titulo_card):
    titulo = titulo_card.upper()
    puesto = info['puesto']
    turnos = info['turnos']
    lugar = info['lugar']
    mins = info['mins_entrada']
    todo_texto = (titulo + info['indicaciones'] + lugar).upper()
    ahora = datetime.now(TZ)

    # --- REGLA DE LIMITACIÓN PARA ESTADIOS (AZTECA / CD DEPORTES) ---
    for estadio in ESTADIOS_LIMITADOS:
        if estadio in todo_texto:
            key = f"{lugar}_{puesto}_{turnos}"
            veces_visto = HISTORIAL_ESTADIOS.get(key, 0)
            if veces_visto >= 5:
                return False, "Límite alcanzado", False
            HISTORIAL_ESTADIOS[key] = veces_visto + 1
            return True, "Estadio (Limitado)", False

    # --- 1. PEPSI CENTER ---
    if "PEPSI CENTER" in todo_texto:
        if puesto in ["SEGURIDAD", "BOLETAJE", "ACOMODADOR EE", "LOCAL CREW"]:
            return True, "PEPSI (Auto)", True

    # --- 2. DIABLOS ---
    if "ALFREDO HARP" in todo_texto or "DIABLOS" in todo_texto:
        if turnos == "1" and puesto in ["SEGURIDAD", "LOCAL CREW", "BOLETAJE"]:
            if "ACOMODADOR" not in puesto: 
                return True, "DIABLOS (Auto)", True

    # --- 3. CCXP ---
    if "CCXP" in todo_texto or "CENTRO BANAMEX" in todo_texto:
        es_nocturna = (mins >= 1170 or mins <= 450)
        if es_nocturna: return True, "CCXP Nocturna (Manual)", False
        if puesto in ["SEGURIDAD", "LOCAL CREW"]:
            fecha_str = info['fecha_dt'].strftime("%d/%m") if info['fecha_dt'] else ""
            if ("23/04" in fecha_str and turnos == "1") or (("24/04" in fecha_str or "25/04" in fecha_str or "26/04" in fecha_str) and turnos == "1.5"):
                return True, "CCXP (Auto)", True

    # --- 4. ESTADIO GNP ---
    if "ESTADIO GNP" in todo_texto:
        if not any(x in todo_texto for x in ["OVG", "ACREDITACIONES"]):
            if (turnos == "1.5" and puesto == "SEGURIDAD") or (turnos == "1" and puesto == "BOLETAJE"):
                es_nocturna = (mins >= 1170 or mins <= 450)
                if not es_nocturna: return True, "GNP (Auto)", True
                elif info['fecha_dt'] and (info['fecha_dt'] - ahora).total_seconds() / 3600 >= 80:
                    return True, "GNP Noct. >80h (Auto)", True

    # --- 5. PALACIO DE LOS DEPORTES ---
    if "PALACIO DE LOS DEPORTES" in todo_texto:
        if 840 <= mins <= 960 and turnos == "1" and puesto in ["SEGURIDAD", "BOLETAJE", "ACOMODADOR EE"]:
            return True, "PALACIO (Auto)", True

    return True, "Nuevo Disponible", False

def run_once():
    global HISTORIAL_ESTADIOS
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0...")
            page = context.new_page()

            page.goto(URL_LOGIN, wait_until="networkidle")
            page.fill("input[name='usuario']", USER)
            page.fill("input[name='password']", PASS)
            page.click("button[type='submit']")
            page.wait_for_timeout(3000)

            page.goto(URL_EVENTS, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            cards = page.query_selector_all(".card.border")
            eventos_resumen = []
            vistos_en_ciclo = set()

            for card in cards:
                if card.evaluate("(node) => node.closest('#div_eventos_confirmados') !== null"): continue
                
                titulo_elem = card.query_selector("h6 a")
                if not titulo_elem: continue
                titulo_texto = titulo_elem.inner_text().strip()

                titulo_elem.click()
                page.wait_for_timeout(1200)
                tabla = card.query_selector(".table-responsive")
                
                if tabla:
                    info = extraer_datos_tabla(tabla.inner_html())
                    interesa, motivo, auto = analizar_filtros(info, titulo_texto)

                    if not interesa: continue

                    if auto:
                        btn = card.query_selector("button:has-text('CONFIRMAR')")
                        if btn:
                            btn.click()
                            page.wait_for_timeout(2500)
                            send(f"🎯 *CONFIRMADO:* {titulo_texto}\n👤 Puesto: {info['puesto']}\n✅ Filtro: {motivo}")
                        else:
                            eventos_resumen.append(f"⚠️ *ERROR BOTÓN:* {titulo_texto} (Criterios OK)")
                    else:
                        emoji = "⚽" if "Estadio" in motivo else "🔔"
                        hora = f"{info['mins_entrada']//60:02d}:{info['mins_entrada']%60:02d}"
                        eventos_resumen.append(f"{emoji} *{titulo_texto}*\n└ {info['puesto']} | {info['turnos']}T | {hora}")
                    
                    vistos_en_ciclo.add(f"{info['lugar']}_{info['puesto']}_{info['turnos']}")

            # Limpiar memoria de estadios antiguos
            HISTORIAL_ESTADIOS = {k: v for k, v in HISTORIAL_ESTADIOS.items() if k in vistos_en_ciclo}

            if eventos_resumen:
                send("📋 *RESUMEN DE EVENTOS*\n\n" + "\n\n".join(eventos_resumen))
            
            browser.close()
    except Exception as e:
        print(f"Error: {e}")

def monitor_loop():
    while True:
        run_once()
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
    
