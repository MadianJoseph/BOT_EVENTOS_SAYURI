import time, re, requests, pytz, os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

# === CONFIGURACIÓN SAYURI (RENDER ENV) ===
USER = os.getenv("WEB_USER")
PASS = os.getenv("WEB_PASS")
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

URL_LOGIN = "https://eventossistema.com.mx/login/default.html"
URL_EVENTS = "https://eventossistema.com.mx/confirmaciones/default.html"
TZ = pytz.timezone("America/Mexico_City")

LUGARES_OK = ["PALACIO DE LOS DEPORTES", "ESTADIO GNP", "AUTODROMO HERMANOS RODRIGUEZ", "ESTADIO ALFREDO HARP HELU", "DIABLOS"]
PUESTOS_NO = ["ACREDITACIONES", "ANFITRION", "MKT", "OVG", "FAN ID", "MODULOS", "TAQUILLA", "CASHLESS", "CCTV", "ACOMODADORA"]
TOP_EVENTS = ["ACDC", "SYSTEM OF A DOWN", "BTS"]

def send(msg):
    if not TOKEN or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 
                      data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def extraer_datos(html):
    d = {"lugar": "", "puesto": "", "turnos": "0", "inicio": "", "fin": ""}
    try:
        lugar = re.search(r'LUGAR</td><td.*?>(.*?)</td>', html, re.I)
        d['lugar'] = lugar.group(1).strip().upper() if lugar else ""
        puesto = re.search(r'PUESTO</td><td.*?>(.*?)</td>', html, re.I)
        d['puesto'] = puesto.group(1).strip().upper() if puesto else ""
        turnos = re.search(r'TURNOS:?\s*([\d.]+)', html, re.I)
        d['turnos'] = turnos.group(1).strip() if turnos else "0"
        horario = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}) AL (\d{2}/\d{2}/\d{4} \d{2}:\d{2})', html)
        if horario:
            d['inicio'], d['fin'] = horario.group(1), horario.group(2)
    except: pass
    return d

def analizar_sayuri(d, titulo, es_bloque):
    ahora = datetime.now(TZ)
    titulo_u = titulo.upper()
    todo_texto = (titulo_u + " " + d['puesto']).upper()

    # 1. TRASLADO / GIRA / BLOQUE
    if any(x in titulo_u for x in ["TRASLADO", "GIRA"]) or es_bloque:
        return False, "⚠️ TRASLADO/GIRA/BLOQUE detectado"

    # 2. EVENTOS TOP (ACDC, SOAD, BTS)
    if any(top in titulo_u for top in TOP_EVENTS):
        return True, "🔥 EVENTO TOP SAYURI 🔥"

    # 3. FILTRO DE LUGAR
    if not any(l in d['lugar'] for l in LUGARES_OK):
        return False, f"📍 Lugar no permitido: {d['lugar']}"

    # 4. FILTRO DE PUESTOS
    if any(p in todo_texto for p in PUESTOS_NO):
        return False, f"🚫 Puesto excluido: {todo_texto}"
    
    # 5. REGLA 84 HORAS
    try:
        inicio_dt = TZ.localize(datetime.strptime(d['inicio'], "%d/%m/%Y %H:%M"))
        if ahora > (inicio_dt - timedelta(hours=84)):
            return False, "⏳ Menos de 84h para el evento"
    except: return False, "❌ Error en fecha"

    # Sayuri acepta domingos temprano, nocturnos y cualquier cantidad de turnos (priorizando altos)
    return True, "✅ CUMPLE FILTROS SAYURI"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page()
        try:
            page.goto(URL_LOGIN)
            page.fill('input[name="usuario"]', USER)
            page.fill('input[name="password"]', PASS)
            page.click('button[type="submit"]')
            page.wait_for_timeout(5000)

            while True:
                page.goto(URL_EVENTS, wait_until="networkidle")
                cont = page.query_selector("#div_eventos_disponibles")
                
                if cont and "No hay eventos" not in cont.inner_text():
                    cards = cont.query_selector_all(".card")
                    for card in cards:
                        link = card.query_selector("h6 a")
                        if not link: continue
                        
                        titulo = link.inner_text().strip()
                        link.click() 
                        page.wait_for_timeout(1500)
                        
                        info = extraer_datos(card.inner_html())
                        es_bloque = "BLOQUE" in card.inner_text().upper()
                        
                        apto, motivo = analizar_sayuri(info, titulo, es_bloque)
                        btn = card.query_selector("button:has-text('CONFIRMAR')")

                        if apto and btn:
                            btn.click()
                            page.wait_for_timeout(2000)
                            if "EVENTO LLENO" in page.content().upper():
                                send(f"❌ SAYURI: EVENTO LLENO\n🎫 {titulo}")
                            else:
                                send(f"✅ SAYURI: CONFIRMADO EXITOSAMENTE\n🎫 {titulo}\n📍 {info['lugar']}\n⏳ {info['turnos']} turnos")
                        else:
                            send(f"📋 SAYURI (DISPONIBLE): {titulo}\n❌ MOTIVO: {motivo}\n📍 Lugar: {info['lugar']}")
                
                time.sleep(90)
                page.reload()
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run()
