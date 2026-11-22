import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import requests
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
if os.getenv("TRUST_LOCAL_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
data = Path(os.getenv("DATA_DIR", "instance"))
data.mkdir(parents=True, exist_ok=True)
secret_file = data / "session.key"
if not os.getenv("SECRET_KEY") and not secret_file.exists():
    try:
        with secret_file.open("x") as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
app.config.update(SECRET_KEY=os.getenv("SECRET_KEY") or secret_file.read_text(),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("HTTPS_ONLY") == "1",
                  MAX_CONTENT_LENGTH=32000, PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
IST = timezone(timedelta(hours=5, minutes=30))
PLACES = {"Bengaluru City Railway Station": (77.5696,12.9784), "Kempegowda International Airport": (77.7066,13.1986),
          "Mysuru Palace": (76.6552,12.3052), "Madikeri Town Centre": (75.7382,12.4244),
          "PES University, Bengaluru": (77.5345,12.9345), "Whitefield, Bengaluru": (77.7499,12.9698),
          "Chikkamagaluru Bus Stand": (75.7754,13.3161)}

@contextmanager
def connect():
    db = sqlite3.connect(data / "fleet.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()

with connect() as db:
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS cars(id INTEGER PRIMARY KEY,name TEXT,fuel TEXT,seats INTEGER,rate REAL,base REAL,minimum REAL,active INTEGER);
    CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,data TEXT,expires INTEGER);
    CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY,quote TEXT UNIQUE,car INTEGER,start INTEGER,end INTEGER,status TEXT,name TEXT,phone TEXT,email TEXT,snapshot TEXT);
    CREATE INDEX IF NOT EXISTS windows ON bookings(car,status,start,end);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,stamp TEXT DEFAULT CURRENT_TIMESTAMP,actor TEXT,action TEXT);
    CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY,booking TEXT,event TEXT,channel TEXT,recipient TEXT,status TEXT DEFAULT 'queued',attempts INTEGER DEFAULT 0,next_try INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY,count INTEGER,expires INTEGER);
    CREATE TABLE IF NOT EXISTS geocache(label TEXT PRIMARY KEY,lon REAL,lat REAL,expires INTEGER);
    CREATE TABLE IF NOT EXISTS geoclock(id INTEGER PRIMARY KEY,slot REAL);
    """)
    if not db.execute("SELECT 1 FROM cars LIMIT 1").fetchone():
        db.executemany("INSERT INTO cars VALUES(?,?,?,?,?,?,?,1)", [(1,"WagonR","Petrol",4,15,100,150),(2,"WagonR","CNG",4,13,100,150),(3,"Tiago EV","Electric",4,12,100,150),(4,"Ertiga","CNG",6,20,150,250)])

@app.before_request
def guard():
    session.setdefault("csrf", secrets.token_urlsafe(24))
    if request.method == "POST":
        if not hmac.compare_digest(session["csrf"],request.form.get("csrf","")):
            abort(403)
        key = f"{request.remote_addr}:{request.endpoint}"
        now = int(time.time())
        with connect() as db:
            db.execute("DELETE FROM limits WHERE expires<=?",(now,))
            db.execute("INSERT INTO limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1",(key,now+600))
            count = db.execute("SELECT count FROM limits WHERE bucket=?",(key,)).fetchone()[0]
        if count > (10 if request.endpoint == "login" else 100):
            abort(429)

@app.after_request
def headers(response):
    response.headers.update({"Cache-Control":"no-store","X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"same-origin"})
    return response

@app.errorhandler(HTTPException)
def error_page(exc):
    messages={400:"Check the details you entered and try again.",
              403:"This form has expired. Open the booking page again.",
              404:"We couldn’t find that page.",
              409:"This booking changed. Refresh the dispatch desk for its latest status.",
              429:"Too many attempts. Please try again in ten minutes."}
    return render_template("error.html",code=exc.code,message=messages.get(exc.code,exc.name)),exc.code

@app.context_processor
def context():
    return dict(brand=os.getenv("BUSINESS_NAME","Mileway"), places=PLACES, contact=os.getenv("CONTACT_PHONE",""), today=datetime.now(IST).date().isoformat())

@app.template_filter("localtime")
def localtime(ts):
    return datetime.fromtimestamp(ts,IST).strftime("%d %b %Y · %I:%M %p IST")

def location(label):
    if label.startswith("Map pin ("):
        point = re.fullmatch(r"Map pin \((-?\d{1,3}(?:\.\d{1,7})?), (-?\d{1,3}(?:\.\d{1,7})?)\)", label)
        if point:
            lat, lon = map(float, point.groups())
            if 6 <= lat <= 38 and 68 <= lon <= 98:
                return lon, lat
        raise ValueError("Choose a map pin within the Indian service region.")
    if label in PLACES:
        return PLACES[label]
    key = label.casefold()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        cached=db.execute("SELECT lon,lat FROM geocache WHERE label=? AND expires>?",(key,time.time())).fetchone()
        if cached: return tuple(cached)
        last=db.execute("SELECT slot FROM geoclock WHERE id=1").fetchone()
        slot=max(time.time(),last[0]+1.1 if last else 0)
        if slot-time.time()>5: raise ValueError("Address lookup is busy. Try a listed landmark or retry shortly.")
        db.execute("INSERT OR REPLACE INTO geoclock VALUES(1,?)",(slot,))
    time.sleep(max(0,slot-time.time()))
    r = requests.get(os.getenv("GEOCODER_URL","https://nominatim.openstreetmap.org/search"),params={"q":label,"countrycodes":"in","limit":1,"format":"json"},headers={"User-Agent":"MilewayFleet/1.0 "+os.getenv("ADMIN_EMAIL","")},timeout=8)
    r.raise_for_status()
    results=r.json()
    if not results:
        raise ValueError("Choose a listed landmark or enter a more specific Indian address.")
    point=float(results[0]["lon"]),float(results[0]["lat"])
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO geocache VALUES(?,?,?,?)",(key,*point,int(time.time())+2592000))
    return point

def route(a,b):
    coords=";".join(f"{x},{y}" for x,y in (a,b))
    r=requests.get(os.getenv("ROUTER_URL","https://router.project-osrm.org").rstrip("/")+"/route/v1/driving/"+coords,params={"overview":"simplified","geometries":"geojson"},timeout=12)
    r.raise_for_status()
    paths=r.json().get("routes",[])
    if not paths or paths[0]["distance"]<100:
        raise ValueError("Choose two distinct places connected by road.")
    return paths[0]

def available(db,car,start,end):
    return db.execute("SELECT 1 FROM cars WHERE id=? AND active=1 AND NOT EXISTS(SELECT 1 FROM bookings WHERE car=? AND status='Approved' AND start<? AND end>?)",(car,car,end,start)).fetchone()

@app.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT id FROM cars LIMIT 1").fetchone()
    return {"status":"ok"}

@app.get("/")
def home():
    with connect() as db:
        cars=db.execute("SELECT * FROM cars WHERE active=1 ORDER BY id").fetchall()
    return render_template("home.html",cars=cars)

@app.post("/quotes")
def quote():
    f=request.form
    try:
        start=int(datetime.fromisoformat(f["date"]+"T"+f["time"]).replace(tzinfo=IST).timestamp())
        if start<=time.time(): raise ValueError("Choose a future pickup time (India Standard Time).")
        pickup,drop=(f[k].strip()[:180] for k in ("pickup","drop"))
        if not pickup or not drop or pickup.casefold()==drop.casefold(): raise ValueError("Enter different pickup and drop locations.")
        trip=f.get("trip","One way")
        if trip not in ("One way","Airport","Round trip"): abort(400)
        a,b=location(pickup),location(drop)
        path=route(a,b)
        distance=path["distance"]
        duration=path["duration"]
        if trip=="Round trip":
            end=int(datetime.fromisoformat(f["return_time"]).replace(tzinfo=IST).timestamp())
            back=route(b,a)
            distance+=back["distance"]
            duration+=back["duration"]
            if end<start+duration: raise ValueError("Allow enough time for both drives before the return trip ends.")
        else: end=start+int(duration)+1800
        km=round(distance/1000,1)
        q=dict(pickup=pickup,drop=drop,origin=f"{a[1]},{a[0]}",destination=f"{b[1]},{b[0]}",trip=trip,start=start,end=end,km=km,minutes=round(duration/60),offers=[],line=path["geometry"]["coordinates"])
        with connect() as db:
            for row in db.execute("SELECT * FROM cars WHERE active=1"):
                if available(db,row["id"],start,end):
                    c=dict(row)
                    c["total"]=round(max(c["minimum"],c["base"]+km*c["rate"]),2)
                    q["offers"].append(c)
            token=uuid4().hex
            db.execute("DELETE FROM quotes WHERE expires<?",(time.time(),))
            db.execute("INSERT INTO quotes VALUES(?,?,?)",(token,json.dumps(q),int(time.time())+900))
        session["quote"]=token
        return render_template("quote.html",q=q,token=token)
    except (requests.RequestException,KeyError,IndexError):
        flash("Road routing is temporarily unavailable. Please try again.")
    except ValueError as e:
        flash("Choose a valid pickup and return date/time." if "isoformat" in str(e) else str(e))
    return redirect(url_for("home"))

def notify(db,bid,event,phone,email):
    targets=[]
    if event in ("Pending","Cancelled"):
        targets.extend([("email",os.getenv("ADMIN_EMAIL")),("whatsapp",os.getenv("ADMIN_PHONE"))])
    if event!="Pending":
        targets.extend([("email",email),("whatsapp",phone)])
    for channel,target in set(targets):
        if target: db.execute("INSERT INTO notices(booking,event,channel,recipient) VALUES(?,?,?,?)",(bid,event,channel,target))

@app.post("/book")
def book():
    import re
    f=request.form
    token=f.get("token","")
    if token!=session.get("quote"): abort(403)
    name=f["name"].strip()
    phone=f["phone"].strip().removeprefix("+91")
    email=f["email"].strip()
    if not 1<len(name)<=100 or not re.fullmatch(r"[6-9]\d{9}",phone) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email) or len(email)>254: abort(400)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old=db.execute("SELECT id FROM bookings WHERE quote=?",(token,)).fetchone()
        if old: bid=old["id"]
        else:
            row=db.execute("SELECT data FROM quotes WHERE id=? AND expires>?",(token,time.time())).fetchone()
            if not row: flash("Your quote expired. Please request a fresh fare."); return redirect("/")
            q=json.loads(row[0])
            car=next((c for c in q.pop("offers") if str(c["id"])==f["car"]),None)
            if not car or q["start"]<=time.time() or not available(db,car["id"],q["start"],q["end"]): flash("This pickup window is unavailable. Please search again."); return redirect("/")
            q["vehicle"]=car
            bid="MW-"+secrets.token_hex(6).upper()
            db.execute("INSERT INTO bookings VALUES(?,?,?,?,?,'Pending',?,?,?,?)",(bid,token,car["id"],q["start"],q["end"],name,phone,email,json.dumps(q)))
            notify(db,bid,"Pending","+91"+phone,email)
    session["receipt"]=bid
    return redirect(url_for("receipt"))

@app.route("/track",methods=["GET","POST"])
def track():
    if request.method=="POST":
        with connect() as db:
            row=db.execute("SELECT id FROM bookings WHERE id=? AND phone=?",(request.form["id"].strip().upper(),request.form["phone"].strip().removeprefix("+91"))).fetchone()
        if row: session["receipt"]=row[0]; return redirect(url_for("receipt"))
        flash("We couldn’t match that reference and mobile number.")
    return render_template("track.html")

@app.get("/receipt")
def receipt():
    with connect() as db: row=db.execute("SELECT * FROM bookings WHERE id=?",(session.get("receipt"),)).fetchone()
    if not row: return redirect("/track")
    return render_template("receipt.html",b=row,q=json.loads(row["snapshot"]))

@app.post("/cancel-request")
def cancel_request():
    bid=session.get("receipt")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM bookings WHERE id=?",(bid,)).fetchone()
        if not row or row["status"]!="Pending": abort(409)
        db.execute("UPDATE bookings SET status='Cancelled' WHERE id=?",(bid,))
        db.execute("INSERT INTO audit(actor,action) VALUES('customer',?)",(bid+" Cancelled",))
        notify(db,bid,"Cancelled","+91"+row["phone"],row["email"])
    return redirect("/receipt")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        key=os.getenv("ADMIN_PASSWORD","")
        if len(key)>=16 and hmac.compare_digest(key.encode(),request.form["password"].encode()):
            session.clear(); session.update(admin=True,csrf=secrets.token_urlsafe(24)); session.permanent=True
            return redirect("/admin")
        flash("Operator sign-in unsuccessful.")
    return render_template("login.html")

@app.post("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/admin",methods=["GET","POST"])
def admin():
    if not session.get("admin"): return redirect("/login")
    with connect() as db:
        if request.method=="POST":
            db.execute("BEGIN IMMEDIATE")
            f=request.form
            if f["action"] in ("fleet","add"):
                vals=[float(f[k]) for k in ("rate","base","minimum")]
                if not all(0<=n<=100000 for n in vals): abort(400)
                name=f["model"].strip()
                fuel=f["fuel"]
                seats=int(f["seats"])
                if not 1<=len(name)<=80 or fuel not in ("Electric","Petrol","CNG","Diesel","Hybrid") or not 1<=seats<=16: abort(400)
                values=(name,fuel,seats,*vals,int("active" in f))
                if f["action"]=="add":
                    row=db.execute("INSERT INTO cars(name,fuel,seats,rate,base,minimum,active) VALUES(?,?,?,?,?,?,?)",values)
                    car_id=row.lastrowid
                else:
                    car_id=int(f["id"])
                    db.execute("UPDATE cars SET name=?,fuel=?,seats=?,rate=?,base=?,minimum=?,active=? WHERE id=?",(*values,car_id))
                action=f"Saved vehicle #{car_id}: {values}"
            else:
                row=db.execute("SELECT * FROM bookings WHERE id=?",(f["id"],)).fetchone()
                state=f["action"]
                if not row or state not in {"Pending":["Approved","Rejected","Cancelled"],"Approved":["Completed","Cancelled"]}.get(row["status"],[]): abort(409)
                if state=="Approved" and not available(db,row["car"],row["start"],row["end"]): flash("Approval blocked. This vehicle is unavailable for the trip window."); return redirect("/admin")
                if state=="Completed" and time.time()<row["start"]: flash("The trip has not started yet."); return redirect("/admin")
                db.execute("UPDATE bookings SET status=? WHERE id=?",(state,row["id"]))
                notify(db,row["id"],state,"+91"+row["phone"],row["email"])
                action=row["id"]+" "+state
            db.execute("INSERT INTO audit(actor,action) VALUES('operator',?)",(action,))
            return redirect("/admin")
        bookings=[(r,json.loads(r["snapshot"])) for r in db.execute("SELECT * FROM bookings ORDER BY CASE status WHEN 'Pending' THEN 0 WHEN 'Approved' THEN 1 ELSE 2 END,start")]
        return render_template("admin.html",bookings=bookings,cars=db.execute("SELECT * FROM cars").fetchall(),logs=db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 30").fetchall(),notices=db.execute("SELECT booking,channel,status FROM notices ORDER BY id DESC LIMIT 30").fetchall())
