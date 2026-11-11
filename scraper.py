"""Marktplaats Multi-Sniper met Web Pushover Schakelaar & Console Logging. 
Start: python scraper.py  ->  http://localhost:8000"""
import json, random, threading, time, pathlib, re
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests

URL = "https://www.marktplaats.nl/lrp/api/search"
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json", "Accept-Language": "nl-NL,nl;q=0.9"}
deals, seen, lock = [], set(), threading.Lock()

# Pushover status variabelen
pushover_status = {"active": True}
PUSHOVER_TOKEN = "a7gaee6d5pq9kvgoreevkku7v7zq5z"
PUSHOVER_USER = "ua9w8mtp93etpk55pnofkbixs1jxhr"

SNIPERS_FILE = pathlib.Path(__file__).parent / "snipers.json"

def get_snipers():
    if SNIPERS_FILE.exists():
        try:
            return json.loads(SNIPERS_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return [{"id": "default", "query": ".", "minPrice": 0, "maxPrice": 0}]

def save_snipers(snipers):
    SNIPERS_FILE.write_text(json.dumps(snipers, indent=2), encoding="utf-8")

def analyseer_live_marktdata(listings, huidige_prijs, titel, desc):
    prijzen = []
    for it in listings:
        p = (it.get("priceInfo") or {}).get("priceCents", 0) // 100
        if 0 < p < 5000:
            prijzen.append(p)
            
    if prijzen:
        prijzen.sort()
        gemiddelde_marktwaarde = int(prijzen[len(prijzen)//2]) if len(prijzen) > 2 else int(sum(prijzen) / len(prijzen))
    else:
        gemiddelde_marktwaarde = 50

    winst = gemiddelde_marktwaarde - huidige_prijs
    advies = "🟢 GRATIS OPHALEN / TOP DEAL" if huidige_prijs == 0 else "🟢 GOEDE DEAL"

    return gemiddelde_marktwaarde, winst, 100, advies

def stuur_pushover_analyse(query, titel, prijs, url, marktwaarde, winst, marge, advies):
    if not pushover_status["active"] or PUSHOVER_TOKEN == "JOUW_API_TOKEN" or PUSHOVER_USER == "JOUW_USER_KEY":
        return
    try:
        bericht = (
            f"🎯 SMART SNIPER HIT: [{query.upper()}]\n"
            f"{advies}\n\n"
            f"💵 Vraagprijs: €{prijs}\n"
            f"📊 Est. Verkoopwaarde: €{marktwaarde}\n"
            f"💰 Est. Netto Winst: €{winst}\n\n"
            f"📌 {titel}"
        )
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
            "message": bericht, "url": url, "url_title": "Bekijk direct op Marktplaats ➔"
        }, timeout=5)
    except Exception as e:
        print("Pushover melding mislukt:", e)

def scan_loop():
    while True:
        snipers = get_snipers()
        for sniper in snipers:
            q = sniper.get("query", ".")
            min_p = float(sniper.get("minPrice", 0) or 0)
            
            max_p_val = sniper.get("maxPrice")
            if max_p_val == "" or max_p_val is None:
                max_p = 100000
            else:
                max_p = float(max_p_val)
            
            try:
                params = {"query": q, "limit": 40, "offset": 0, "sortBy": "SORT_INDEX", "sortOrder": "DECREASING", "postcode": "5503BA", "distanceMeters": 30000}
                r = requests.get(URL, headers=HEAD, timeout=15, params=params)
                if not r.ok: continue
                listings = r.json().get("listings", [])
                for it in listings:
                    iid = str(it.get("itemId"))
                    
                    price_info = it.get("priceInfo") or {}
                    price_type = price_info.get("priceType", "")
                    price = price_info.get("priceCents", 0) // 100
                    
                    if price_type == "GRATIS":
                        price = 0

                    if iid in seen:
                        continue
                    
                    if price < min_p or price > max_p:
                        continue
                        
                    seen.add(iid)
                    title = it.get("title", "")
                    desc = it.get("description", "") or it.get("categorySpecificDescription", "") or ""
                    url = it.get("vipUrl", "")
                    url = url if url.startswith("http") else "https://www.marktplaats.nl" + url
                    images = it.get("images", [])
                    image_url = (images[0].get("smallUrl") or images[0].get("largeUrl") or "") if images else ""
                    
                    marktwaarde, winst, marge, advies = analyseer_live_marktdata(listings, price, title, desc)
                    with lock:
                        deals.insert(0, {
                            "id": iid, "title": title, "desc": desc, "price": price,
                            "url": url, "image": image_url, "query": q, "geplaatst": "Zojuist",
                            "est_waarde": marktwaarde, "winst": winst, "marge": marge, "advies": advies
                        })
                        del deals[200:]
                    
                    tijdstip = datetime.now().strftime("%H:%M:%S")
                    print(f"[{tijdstip}] 🎯 Sniper [{q}] Hit! Vraag: €{price} | Winst est: €{winst} | {title[:40]}")
                    
                    stuur_pushover_analyse(q, title, price, url, marktwaarde, winst, marge, advies)
                time.sleep(2)
            except Exception as e:
                print(f"Fout bij sniper {q}:", e)
        time.sleep(40)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/deals"):
            with lock:
                body, ctype = json.dumps(deals).encode(), "application/json"
        elif self.path.startswith("/api/snipers"):
            body, ctype = json.dumps(get_snipers()).encode(), "application/json"
        elif self.path.startswith("/api/pushover-status"):
            body, ctype = json.dumps(pushover_status).encode(), "application/json"
        else:
            try:
                html_path = pathlib.Path(__file__).parent / "index.html"
                body, ctype = html_path.read_bytes(), "text/html; charset=utf-8"
            except Exception as e:
                body = f"<!DOCTYPE html><html><body><h2>⚠️ Kan index.html niet vinden: {e}</h2></body></html>".encode()
                ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/snipers"):
            length = int(self.headers.get('content-length', 0))
            data = json.loads(self.rfile.read(length).decode())
            snipers = get_snipers()
            data["id"] = str(int(time.time()*1000))
            snipers.append(data)
            save_snipers(snipers)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        elif self.path.startswith("/api/pushover-toggle"):
            length = int(self.headers.get('content-length', 0))
            data = json.loads(self.rfile.read(length).decode())
            pushover_status["active"] = bool(data.get("active", True))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(pushover_status).encode())
        elif self.path.startswith("/api/taxeer"):
            length = int(self.headers.get('content-length', 0))
            req = json.loads(self.rfile.read(length).decode())
            prompt = req.get("prompt", "").lower()
            query = req.get("query", "iphone 15").lower()
            cost = float(req.get("cost", 0) or 0)
            
            try:
                base_prijzen = {
                    "iphone 17 pro max": 930, "iphone 17 pro": 830, "iphone 17": 690,
                    "iphone 16 pro max": 680, "iphone 16 pro": 590, "iphone 16": 475,
                    "iphone 15 pro max": 565, "iphone 15 pro": 475, "iphone 15": 350,
                    "iphone 14 pro max": 420, "iphone 14 pro": 360, "iphone 14": 290,
                    "iphone 13 pro max": 350, "iphone 13 pro": 295, "iphone 13": 245,
                    "iphone 12 pro max": 230, "iphone 12 pro": 200, "iphone 12": 140,
                    "iphone 11 pro max": 185, "iphone 11 pro": 155, "iphone 11": 125
                }
                ref_markt = 350
                for model_naam, prijs_val in base_prijzen.items():
                    if model_naam in prompt:
                        ref_markt = prijs_val
                        break
                
                if ref_markt == 350 and not any(m in prompt for m in base_prijzen.keys()):
                    params = {"query": query, "limit": 30, "postcode": "5503BA", "distanceMeters": 30000}
                    r = requests.get(URL, headers=HEAD, timeout=15, params=params)
                    listings = r.json().get("listings", []) if r.ok else []
                    prijzen = [(it.get("priceInfo") or {}).get("priceCents", 0) // 100 for it in listings]
                    prijzen = [p for p in prijzen if 20 < p < 5000]
                    if prijzen:
                        ref_markt = int(sum(prijzen) / len(prijzen))

                multiplier = 1.0
                note = "Nette gebruikte staat."
                if "geen schade" in prompt or "netjes" in prompt or "zgan" in prompt:
                    multiplier += 0.05
                if "schade" in prompt or "barst" in prompt or "kras" in prompt or "deuk" in prompt:
                    multiplier -= 0.30
                if "defect" in prompt or "kapot" in prompt:
                    multiplier -= 0.50

                finalVal = int(ref_markt * multiplier)
                winst = int(finalVal - cost) if cost > 0 else 0
                res_data = {"val": finalVal, "avg": ref_markt, "note": note, "winst": winst}
                body = json.dumps(res_data).encode()
            except Exception as e:
                body = json.dumps({"error": str(e)}).encode()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    def do_DELETE(self):
        if self.path.startswith("/api/snipers/"):
            sid = self.path.split("/")[-1]
            snipers = [s for s in get_snipers() if s.get("id") != sid]
            save_snipers(snipers)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *a): pass

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    threading.Thread(target=scan_loop, daemon=True).start()
    print(f"Open http://localhost:{port} (Web Pushover Schakelaar Actief)")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()