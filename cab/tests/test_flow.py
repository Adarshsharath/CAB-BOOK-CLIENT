import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

storage = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = storage.name
from app import app, connect, IST, location
from notify import process


class BookingFlow(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.get("/")
        self.route = patch("app.route", return_value={
            "distance": 20000, "duration": 2400,
            "geometry": {"coordinates": [[77.57,12.98],[77.7,13.2]]}})
        self.route.start()
        self.addCleanup(self.route.stop)

    def post(self, path, **fields):
        with self.client.session_transaction() as session:
            fields["csrf"] = session["csrf"]
        return self.client.post(path, data=fields, follow_redirects=True)

    def request_cab(self):
        date = (datetime.now(IST)+timedelta(days=2)).date().isoformat()
        response = self.post("/quotes",pickup="Bengaluru City Railway Station",
            drop="Kempegowda International Airport",date=date,time="09:00")
        self.assertIn(b"Available vehicles", response.data)
        with self.client.session_transaction() as session: token=session["quote"]
        fields=dict(token=token,car="1",name="Test Rider",phone="9000000000",email="test@example.test")
        self.assertIn(b"awaiting operator approval",self.post("/book",**fields).data)
        self.post("/book",**fields)
        with self.client.session_transaction() as session: return session["receipt"]

    def test_approval_conflict_and_release(self):
        first, second = self.request_cab(), self.request_cab()
        with patch.dict(os.environ,ADMIN_PASSWORD="isolated-test-password"):
            self.assertIn(b"Dispatch desk",self.post("/login",password="isolated-test-password").data)
        self.post("/admin",id=first,action="Approved")
        self.assertIn(b"Approval blocked",self.post("/admin",id=second,action="Approved").data)
        self.post("/admin",id=first,action="Cancelled")
        self.post("/admin",id=second,action="Approved")
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM bookings").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT status FROM bookings WHERE id=?",(second,)).fetchone()[0],"Approved")
        self.post("/logout")
        self.assertIn(b"Approved",self.post("/track",id=second,phone="9000000000").data)
        with patch.dict(os.environ,clear=True):
            self.assertFalse(process())
        settings=dict(SMTP_HOST="test.example",SMTP_FROM="dispatch@example.test",
                      SMTP_USER="operator",SMTP_PASSWORD="fixture")
        with patch.dict(os.environ,settings,clear=True), patch("notify.deliver") as deliver:
            self.assertTrue(process())
            job=deliver.call_args.args[0]
            self.assertEqual(job["channel"],"email")
            with connect() as db:
                state=db.execute("SELECT status FROM notices WHERE id=?",(job["id"],)).fetchone()[0]
            self.assertEqual(state,"sent")

    def test_admin_requires_auth_and_posts_require_csrf(self):
        self.assertEqual(self.client.get("/admin").location,"/login")
        self.assertEqual(self.client.post("/book").status_code,403)

    def test_map_pins_use_router_coordinate_order(self):
        with patch("app.requests.get") as geocoder:
            self.assertEqual(location("Map pin (12.97840, 77.56960)"), (77.5696, 12.9784))
            for label in ("Map pin (invalid)", "Map pin (100.0, 77.0)"):
                with self.assertRaises(ValueError):
                    location(label)
            geocoder.assert_not_called()
