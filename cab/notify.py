"""Run one delivery worker alongside the web service."""
import json
import logging
import os
import smtplib
import ssl
import time
import sqlite3
import threading
from email.message import EmailMessage

import requests

from app import connect, localtime

def deliver(job):
    snap = json.loads(job["snapshot"])
    details = [
        job["booking"], job["event"], snap["pickup"], snap["drop"],
        localtime(snap["start"]), snap["vehicle"]["name"],
        f"INR {snap['vehicle']['total']:.2f} plus tolls and parking",
    ]
    if job["channel"] == "email":
        msg = EmailMessage()
        msg["Subject"] = f"Booking {details[0]} · {details[1]}"
        msg["From"] = os.environ["SMTP_FROM"]
        msg["To"] = job["recipient"]
        msg.set_content("\n".join(details))
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT","587")), timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        payload = {"messaging_product":"whatsapp","to":job["recipient"].lstrip("+"),"type":"template",
                   "template":{"name":os.environ["WA_TEMPLATE"],"language":{"code":os.getenv("WA_LANGUAGE","en")},
                               "components":[{"type":"body","parameters":[{"type":"text","text":x} for x in details]}]}}
        res = requests.post(os.environ["WA_MESSAGES_URL"], json=payload, timeout=15,
                            headers={"Authorization":"Bearer "+os.environ["WA_TOKEN"]})
        res.raise_for_status()

def process():
    channels = []
    if all(os.getenv(k) for k in ("SMTP_HOST","SMTP_FROM","SMTP_USER","SMTP_PASSWORD")):
        channels.append("email")
    if all(os.getenv(k) for k in ("WA_MESSAGES_URL","WA_TOKEN","WA_TEMPLATE")):
        channels.append("whatsapp")
    if not channels:
        return False
    placeholders = ",".join("?" for _ in channels)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(f"""SELECT n.*,b.snapshot FROM notices n JOIN bookings b ON b.id=n.booking
            WHERE n.status IN ('queued','retry','sending') AND n.next_try<=? AND n.channel IN ({placeholders})
            ORDER BY n.id LIMIT 1""",(time.time(),*channels)).fetchone()
        if not job: return False
        db.execute("UPDATE notices SET status='sending', next_try=? WHERE id=?", (int(time.time())+120,job["id"]))
    attempt = job["attempts"]+1
    try:
        deliver(job)
        state = "sent"
    except (ValueError, KeyError, OSError, requests.RequestException, smtplib.SMTPException) as exc:
        logging.warning("Delivery %s attempt %s: %s",job["id"],attempt,type(exc).__name__)
        state = "failed" if attempt>=10 else "retry"
    with connect() as db:
        db.execute("UPDATE notices SET status=?,attempts=?,next_try=? WHERE id=?",(state,attempt,int(time.time())+min(3600,30*2**attempt),job["id"]))
    return True

def run_worker(stop):
    while not stop.is_set():
        try:
            if process():
                continue
        except sqlite3.Error:
            logging.exception("Notification database temporarily unavailable")
        stop.wait(5)

if __name__=="__main__":
    run_worker(threading.Event())
