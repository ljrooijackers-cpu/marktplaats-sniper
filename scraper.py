"""Marktplaats Multi-Sniper met Web Pushover Schakelaar & Console Logging. 
Start: python scraper.py  ->  http://localhost:8000"""
import json, threading, pathlib
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests

URL = "https://www.marktplaats.nl/lrp/api/search"
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json", "Accept-Language": "nl-NL,nl;q=0.9"}

pushover_status = {"active": True}
PUSHOVER_TOKEN = "a7gaee6d5pq9kvgoreevkku7v7zq5z"
PUSHOVER_USER = "ua9w8mtp93etpk55pnofkbixs1jxhr"

def stuur_pushover_melding(query, titel, prijs_display, url):
    if not pushover_status["active"]:
        return
    try:
        bericht = (
            f"🎯 SNIPER HIT: [{query.upper()}]\n\n"
            f"💵 Vraagprijs: {prijs_display}\n\n"
            f"📌 {titel}"
        )
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
            "message": bericht, "url": url, "url_title": "Bekijk direct op Marktplaats ➔"
        }, timeout=5)
    except Exception as e:
        print("Pushover melding mislukt:", e)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/pushover-status"):
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
        if self.path.startswith("/api/scan-item"):
            length = int(self.headers.get('content-length', 0))
            data = json.loads(self.rfile.read(length).decode())
            snipers = data.get("snipers", [])
            found_deals = []
            
            for sniper in snipers:
                q = sniper.get("query", ".")
                min_p = float(sniper.get("minPrice", 0) or 0)
                max_p_val = sniper.get("maxPrice")
                max_p = 100000 if (max_p_val == "" or max_p_val is None) else float(max_p_val)
                
                try:
                    params = {"query": q, "limit": 20, "offset": 0, "sortBy": "SORT_INDEX", "sortOrder": "DECREASING", "postcode": "5503BA", "distanceMeters": 30000}
                    r = requests.get(URL, headers=HEAD, timeout=15, params=params)
                    if not r.ok: continue
                    listings = r.json().get("listings", [])
                    for it in listings:
                        iid = str(it.get("itemId"))
                        price_info = it.get("priceInfo") or {}
                        price_type = price_info.get("priceType", "")
                        price_cents = price_info.get("priceCents", 0)
                        price = price_cents // 100
                        
                        if price_type == "GRATIS":
                            price_val = 0
                            price_display = "Gratis"
                        elif price_type in ["BIEDEN", "BID", "MARKTPIJS"] or price_cents == 0:
                            price_val = 0
                            price_display = "Bieden"
                        else:
                            price_val = price
                            price_display = f"€{price}"
                        
                        if price_type == "FIXED" and (price_val < min_p or price_val > max_p):
                            continue
                            
                        title = it.get("title", "")
                        desc = it.get("description", "") or it.get("categorySpecificDescription", "") or ""
                        url = it.get("vipUrl", "")
                        url = url if url.startswith("http") else "https://www.marktplaats.nl" + url
                        images = it.get("images", [])
                        image_url = (images[0].get("smallUrl") or images[0].get("largeUrl") or "") if images else ""
                        
                        found_deals.append({
                            "id": iid, "title": title, "desc": desc, "price": price_val,
                            "price_display": price_display, "url": url, "image": image_url, "query": q, "geplaatst": "Zojuist"
                        })
                        
                        tijdstip = datetime.now().strftime("%H:%M:%S")
                        print(f"[{tijdstip}] 🎯 Sniper [{q}] Hit! Vraag: {price_display} | {title[:40]}")
                        stuur_pushover_melding(q, title, price_display, url)
                except Exception as e:
                    print(f"Fout bij sniper {q}:", e)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(found_deals).encode())

        elif self.path.startswith("/api/pushover-toggle"):
            length = int(self.headers.get('content-length', 0))
            data = json.loads(self.rfile.read(length).decode())
            pushover_status["active"] = bool(data.get("active", True))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(pushover_status).encode())

    def log_message(self, *a): pass

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    print(f"Open http://localhost:{port} (Persoonlijke Browser-Snipers Actief)")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
