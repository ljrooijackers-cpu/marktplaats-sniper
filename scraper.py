"""Marktplaats Multi-Sniper met Account Systeem & Database. 
Start: python scraper.py  ->  http://localhost:8000"""
import json, threading, pathlib, sqlite3, hashlib, time
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import requests

URL = "https://www.marktplaats.nl/lrp/api/search"
HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json", "Accept-Language": "nl-NL,nl;q=0.9"}

DB_FILE = pathlib.Path(__file__).parent / "users.db"

pushover_status = {"active": True}
PUSHOVER_TOKEN = "a7gaee6d5pq9kvgoreevkku7v7zq5z"
PUSHOVER_USER = "ua9w8mtp93etpk55pnofkbixs1jxhr"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    password TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS snipers (
                    id TEXT,
                    user_id INTEGER,
                    query TEXT,
                    min_price REAL,
                    max_price REAL,
                    PRIMARY KEY(id, user_id)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS ignored (
                    item_id TEXT,
                    user_id INTEGER,
                    PRIMARY KEY(item_id, user_id)
                )''')
    conn.commit()
    conn.close()

init_db()

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()

def stuur_pushover_melding(query, titel, prijs_display, url):
    if not pushover_status["active"]:
        return
    try:
        bericht = f"🎯 SNIPER HIT: [{query.upper()}]\n\nVraagprijs: {prijs_display}\n📌 {titel}"
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
            "message": bericht, "url": url, "url_title": "Bekijk op Marktplaats ➔"
        }, timeout=5)
    except:
        pass

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
        length = int(self.headers.get('content-length', 0))
        data = json.loads(self.rfile.read(length).decode()) if length > 0 else {}
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        response_data = {}
        status_code = 200

        if self.path.startswith("/api/register"):
            username = data.get("username", "").strip()
            password = hash_pw(data.get("password", ""))
            try:
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                response_data = {"status": "ok", "user_id": c.lastrowid}
            except:
                status_code = 400
                response_data = {"error": "Gebruikersnaam bestaat al."}

        elif self.path.startswith("/api/login"):
            username = data.get("username", "").strip()
            password = hash_pw(data.get("password", ""))
            c.execute("SELECT id FROM users WHERE username = ? AND password = ?", (username, password))
            row = c.fetchone()
            if row:
                response_data = {"status": "ok", "user_id": row[0]}
            else:
                status_code = 401
                response_data = {"error": "Onjuiste gegevens."}

        elif self.path.startswith("/api/snipers/get"):
            user_id = data.get("user_id")
            c.execute("SELECT id, query, min_price, max_price FROM snipers WHERE user_id = ?", (user_id,))
            snipers = [{"id": r[0], "query": r[1], "minPrice": r[2], "maxPrice": r[3]} for r in c.fetchall()]
            response_data = snipers

        elif self.path.startswith("/api/snipers/add"):
            user_id = data.get("user_id")
            s = data.get("sniper", {})
            c.execute("INSERT OR REPLACE INTO snipers (id, user_id, query, min_price, max_price) VALUES (?, ?, ?, ?, ?)",
                      (s.get("id"), user_id, s.get("query"), s.get("minPrice"), s.get("maxPrice")))
            conn.commit()
            response_data = {"status": "ok"}

        elif self.path.startswith("/api/snipers/delete"):
            user_id = data.get("user_id")
            sid = data.get("id")
            c.execute("DELETE FROM snipers WHERE id = ? AND user_id = ?", (sid, user_id))
            conn.commit()
            response_data = {"status": "ok"}

        elif self.path.startswith("/api/ignored/get"):
            user_id = data.get("user_id")
            c.execute("SELECT item_id FROM ignored WHERE user_id = ?", (user_id,))
            response_data = [r[0] for r in c.fetchall()]

        elif self.path.startswith("/api/ignored/add"):
            user_id = data.get("user_id")
            item_id = data.get("item_id")
            c.execute("INSERT OR IGNORE INTO ignored (item_id, user_id) VALUES (?, ?)", (item_id, user_id))
            conn.commit()
            response_data = {"status": "ok"}

        elif self.path.startswith("/api/ignored/clear"):
            user_id = data.get("user_id")
            c.execute("DELETE FROM ignored WHERE user_id = ?", (user_id,))
            conn.commit()
            response_data = {"status": "ok"}

        elif self.path.startswith("/api/scan-item"):
            user_id = data.get("user_id")
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
                            price_val, price_display = 0, "Gratis"
                        elif price_type in ["BIEDEN", "BID", "MARKTPIJS"] or price_cents == 0:
                            price_val, price_display = 0, "Bieden"
                        else:
                            price_val, price_display = price, f"€{price}"
                        
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
                        
                        stuur_pushover_melding(q, title, price_display, url)
                except Exception as e:
                    print("Scan fout:", e)
            
            response_data = found_deals

        elif self.path.startswith("/api/pushover-toggle"):
            pushover_status["active"] = bool(data.get("active", True))
            response_data = pushover_status

        conn.close()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())

    def log_message(self, *a): pass

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    print(f"Open http://localhost:{port} (Account Systeem Actief)")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
