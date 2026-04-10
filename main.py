import os
import sqlite3
import uuid
import math
import asyncio
import hashlib
import secrets
import random
import string
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

import httpx
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from fastapi import FastAPI, Request, HTTPException, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

INTASEND_API_KEY   = os.environ.get("INTASEND_API_KEY", "")
INTASEND_BASE_URL  = os.environ.get("INTASEND_BASE_URL", "https://sandbox.intasend.com")
SMTP_USER          = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD      = os.environ.get("SMTP_PASSWORD", "")
ADMIN_EMAIL        = "ronoellykibet@gmail.com"
DATABASE_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wellparks.db")
STATIC_DIR         = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
HOURLY_RATE        = 50
GRACE_MINUTES      = 0
TOTAL_SPACES       = 500
SESSION_HOURS      = 24
OTP_MINUTES        = 10

ADMIN_EMAIL_LOGIN  = "ronoellykibet@gmail.com"
ADMIN_PASSWORD_RAW = "Elly@Elly123"


def hash_password(password: str, salt: str = "wellparks_secure_2026") -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS spaces (
            id INTEGER PRIMARY KEY,
            space_number INTEGER UNIQUE NOT NULL,
            is_occupied BOOLEAN DEFAULT 0,
            plate_number TEXT,
            driver_phone TEXT,
            driver_email TEXT,
            entry_time TEXT
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT NOT NULL,
            driver_phone TEXT,
            driver_email TEXT,
            space_number INTEGER,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            duration_minutes REAL,
            amount REAL,
            transaction_ref TEXT,
            payment_status TEXT DEFAULT 'PENDING',
            gate_status TEXT DEFAULT 'CLOSED',
            intasend_invoice_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT 'Admin',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admin_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            admin_email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_email TEXT,
            recipient_plate TEXT,
            subject TEXT,
            message TEXT,
            type TEXT DEFAULT 'SYSTEM',
            sent_at TEXT DEFAULT (datetime('now')),
            status TEXT DEFAULT 'SENT'
        );

        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            message TEXT,
            sent_by TEXT,
            sent_at TEXT DEFAULT (datetime('now')),
            recipient_count INTEGER DEFAULT 0
        );
    """)

    existing_spaces = conn.execute("SELECT COUNT(*) FROM spaces").fetchone()[0]
    if existing_spaces == 0:
        conn.executemany(
            "INSERT INTO spaces (space_number, is_occupied) VALUES (?, 0)",
            [(i,) for i in range(1, TOTAL_SPACES + 1)]
        )

    existing_admin = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
    if existing_admin == 0:
        conn.execute(
            "INSERT INTO admin_users (email, password_hash, name) VALUES (?, ?, ?)",
            (ADMIN_EMAIL_LOGIN, hash_password(ADMIN_PASSWORD_RAW), "Admin")
        )

    conn.commit()
    conn.close()


async def send_email(to_email: str, subject: str, html_body: str):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[Email skipped - no SMTP] {subject} -> {to_email}")
        return
    message = MIMEMultipart("alternative")
    message["From"] = SMTP_USER
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(html_body, "html"))
    try:
        await aiosmtplib.send(
            message,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
        )
        print(f"[Email sent] {subject} -> {to_email}")
    except Exception as e:
        print(f"[Email error] {e}")


def log_notification(recipient_email: str, recipient_plate: str, subject: str, message: str, notif_type: str = "SYSTEM"):
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO notifications (recipient_email, recipient_plate, subject, message, type) VALUES (?,?,?,?,?)",
            (recipient_email, recipient_plate, subject, message[:500], notif_type)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Notification log error] {e}")


async def send_otp_email(email: str, code: str):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;background:#1a1f36;color:#fff;padding:36px;border-radius:12px;">
        <h2 style="color:#84cc16;margin-bottom:8px;">WellParks Admin</h2>
        <p style="color:#94a3b8;margin-bottom:24px;">Your one-time login code</p>
        <div style="background:#0f1221;border:2px solid #84cc16;border-radius:10px;padding:24px;text-align:center;margin-bottom:24px;">
            <div style="font-size:3rem;font-weight:800;letter-spacing:12px;color:#84cc16;">{code}</div>
        </div>
        <p style="color:#94a3b8;font-size:.85rem;">This code expires in {OTP_MINUTES} minutes. Never share it with anyone.</p>
    </div>
    """
    await send_email(email, "WellParks Admin - Your OTP Code", html)


async def send_entry_notification_admin(plate, phone, email, space_number, timestamp):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#1a1f36;color:#fff;padding:30px;border-radius:12px;">
        <h2 style="color:#84cc16;">&#128663; New Vehicle Entry</h2>
        <hr style="border-color:#2d3250;margin:16px 0;">
        <table style="width:100%;color:#ccc;line-height:2.2;">
            <tr><td style="color:#94a3b8;width:40%">Plate Number</td><td><strong style="color:#fff;">{plate}</strong></td></tr>
            <tr><td style="color:#94a3b8;">Phone</td><td>{phone}</td></tr>
            <tr><td style="color:#94a3b8;">Email</td><td>{email}</td></tr>
            <tr><td style="color:#94a3b8;">Space</td><td><strong>#{space_number}</strong></td></tr>
            <tr><td style="color:#94a3b8;">Entry Time</td><td>{timestamp}</td></tr>
        </table>
        <hr style="border-color:#2d3250;margin:16px 0;">
        <p style="color:#94a3b8;font-size:.85rem;text-align:center;">WellParks Parking Management System</p>
    </div>
    """
    await send_email(ADMIN_EMAIL, f"WellParks: Vehicle Entry - {plate}", html)
    log_notification(ADMIN_EMAIL, plate, f"Vehicle Entry - {plate}", f"Plate {plate} entered space #{space_number}", "ENTRY")


async def send_driver_entry_notification(plate, phone, email, space_number, timestamp):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#1a1f36;color:#fff;padding:30px;border-radius:12px;">
        <h2 style="color:#84cc16;">&#128663; Welcome to WellParks!</h2>
        <p style="color:#94a3b8;margin-bottom:20px;">Your vehicle has been registered in our parking facility.</p>
        <div style="background:#0f1221;border-radius:8px;padding:20px;margin-bottom:20px;">
            <table style="width:100%;color:#ccc;line-height:2.2;">
                <tr><td style="color:#94a3b8;width:40%">Plate Number</td><td><strong style="color:#84cc16;">{plate}</strong></td></tr>
                <tr><td style="color:#94a3b8;">Parking Space</td><td><strong>#{space_number}</strong></td></tr>
                <tr><td style="color:#94a3b8;">Entry Time</td><td>{timestamp}</td></tr>
                <tr><td style="color:#94a3b8;">Rate</td><td>KES 50 / hour</td></tr>
            </table>
        </div>
        <p style="color:#94a3b8;font-size:.85rem;">Payment is via M-Pesa STK Push when you exit. Thank you for parking with WellParks!</p>
    </div>
    """
    await send_email(email, f"WellParks: Entry Confirmation - Space #{space_number}", html)
    log_notification(email, plate, f"Entry Confirmation - Space #{space_number}", f"Vehicle {plate} registered in space #{space_number}", "ENTRY")


async def send_receipt_email(to_email, plate, entry_time, exit_time, duration, amount, ref):
    hours = int(duration // 60)
    mins = int(duration % 60)
    duration_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#1a1f36;color:#fff;padding:30px;border-radius:12px;">
        <h2 style="color:#84cc16;">&#9989; Payment Receipt</h2>
        <p style="color:#94a3b8;margin-bottom:20px;">Your parking payment has been received.</p>
        <div style="background:#0f1221;border-radius:8px;padding:20px;margin-bottom:20px;">
            <table style="width:100%;color:#ccc;line-height:2.2;">
                <tr><td style="color:#94a3b8;width:40%">Plate Number</td><td><strong style="color:#84cc16;">{plate}</strong></td></tr>
                <tr><td style="color:#94a3b8;">Entry Time</td><td>{entry_time}</td></tr>
                <tr><td style="color:#94a3b8;">Exit Time</td><td>{exit_time}</td></tr>
                <tr><td style="color:#94a3b8;">Duration</td><td>{duration_str}</td></tr>
                <tr><td style="color:#94a3b8;">Amount Paid</td><td><strong style="color:#84cc16;">KES {amount:.2f}</strong></td></tr>
                <tr><td style="color:#94a3b8;">M-Pesa Ref</td><td><code style="color:#84cc16;">{ref}</code></td></tr>
            </table>
        </div>
        <p style="color:#84cc16;text-align:center;font-size:1rem;">Thank you for parking with WellParks! Drive safely. &#128663;</p>
    </div>
    """
    await send_email(to_email, f"WellParks Receipt - {plate}", html)
    if ADMIN_EMAIL and to_email != ADMIN_EMAIL:
        await send_email(ADMIN_EMAIL, f"WellParks Receipt Copy - {plate}", html)
    log_notification(to_email, plate, f"Payment Receipt - {plate}", f"KES {amount:.2f} paid for {plate}, ref: {ref}", "RECEIPT")


async def poll_intasend_status():
    while True:
        try:
            conn = get_db()
            pending = conn.execute(
                "SELECT * FROM transactions WHERE payment_status='PENDING' AND intasend_invoice_id IS NOT NULL"
            ).fetchall()
            conn.close()
            for txn in pending:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            f"{INTASEND_BASE_URL}/api/v1/payment/status/",
                            params={"invoice_id": txn["intasend_invoice_id"]},
                            headers={"Authorization": f"Bearer {INTASEND_API_KEY}"},
                            timeout=10,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            state = data.get("invoice", {}).get("state", "").upper()
                            if state == "COMPLETE":
                                mpesa_ref = data.get("invoice", {}).get("mpesa_reference", txn["transaction_ref"])
                                conn2 = get_db()
                                conn2.execute(
                                    "UPDATE transactions SET payment_status='COMPLETED', gate_status='OPEN', transaction_ref=? WHERE id=?",
                                    (mpesa_ref, txn["id"]),
                                )
                                conn2.execute(
                                    "UPDATE spaces SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL WHERE space_number=?",
                                    (txn["space_number"],),
                                )
                                conn2.commit()
                                conn2.close()
                                asyncio.create_task(send_receipt_email(
                                    txn["driver_email"], txn["plate_number"],
                                    txn["entry_time"], txn["exit_time"],
                                    txn["duration_minutes"], txn["amount"], mpesa_ref,
                                ))
                except Exception as e:
                    print(f"[Poll error txn {txn['id']}] {e}")
        except Exception as e:
            print(f"[Poll loop error] {e}")
        await asyncio.sleep(3)


def get_session_admin(request: Request) -> Optional[str]:
    token = request.cookies.get("wp_session")
    if not token:
        return None
    conn = get_db()
    session = conn.execute(
        "SELECT * FROM admin_sessions WHERE token=?", (token,)
    ).fetchone()
    conn.close()
    if not session:
        return None
    expires = datetime.fromisoformat(session["expires_at"])
    if datetime.now(timezone.utc) > expires:
        return None
    return session["admin_email"]


def require_admin(request: Request) -> str:
    admin = get_session_admin(request)
    if not admin:
        raise HTTPException(401, "Unauthorized - please login")
    return admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(poll_intasend_status())
    yield
    task.cancel()


app = FastAPI(title="WellParks", lifespan=lifespan)


class EntryRequest(BaseModel):
    plate_number: str
    driver_phone: str
    driver_email: str
    space_number: int


class ExitLookupRequest(BaseModel):
    plate_number: str


class PaymentInitRequest(BaseModel):
    plate_number: str


class LoginRequest(BaseModel):
    email: str
    password: str


class OTPVerifyRequest(BaseModel):
    email: str
    code: str


class BroadcastRequest(BaseModel):
    subject: str
    message: str
    recipient: str = "all"


class MessageRequest(BaseModel):
    email: str
    plate: str
    subject: str
    message: str


@app.post("/v1/auth/login")
async def admin_login(req: LoginRequest):
    if req.email.lower() != ADMIN_EMAIL_LOGIN.lower():
        raise HTTPException(401, "Invalid credentials")
    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM admin_users WHERE email=?", (req.email.lower(),)
    ).fetchone()
    conn.close()
    if not admin:
        raise HTTPException(401, "Invalid credentials")
    expected = hash_password(req.password)
    if admin["password_hash"] != expected:
        raise HTTPException(401, "Invalid credentials")
    code = "".join(random.choices(string.digits, k=6))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=OTP_MINUTES)).isoformat()
    conn2 = get_db()
    conn2.execute("DELETE FROM otp_codes WHERE email=?", (req.email.lower(),))
    conn2.execute(
        "INSERT INTO otp_codes (email, code, expires_at) VALUES (?, ?, ?)",
        (req.email.lower(), code, expires)
    )
    conn2.commit()
    conn2.close()
    asyncio.create_task(send_otp_email(ADMIN_EMAIL, code))
    return {"status": "otp_sent", "message": f"OTP sent to {ADMIN_EMAIL}"}


@app.post("/v1/auth/verify-otp")
async def verify_otp(req: OTPVerifyRequest):
    conn = get_db()
    otp = conn.execute(
        "SELECT * FROM otp_codes WHERE email=? AND code=? AND used=0 ORDER BY id DESC LIMIT 1",
        (req.email.lower(), req.code)
    ).fetchone()
    if not otp:
        conn.close()
        raise HTTPException(401, "Invalid or expired OTP code")
    expires = datetime.fromisoformat(otp["expires_at"])
    if datetime.now(timezone.utc) > expires:
        conn.close()
        raise HTTPException(401, "OTP has expired. Please login again.")
    conn.execute("UPDATE otp_codes SET used=1 WHERE id=?", (otp["id"],))
    token = secrets.token_urlsafe(48)
    session_expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
    conn.execute(
        "INSERT INTO admin_sessions (token, admin_email, expires_at) VALUES (?, ?, ?)",
        (token, req.email.lower(), session_expires)
    )
    conn.commit()
    conn.close()
    response = JSONResponse({"status": "ok", "email": req.email})
    response.set_cookie(
        "wp_session", token,
        httponly=True, max_age=SESSION_HOURS * 3600, samesite="lax"
    )
    return response


@app.post("/v1/auth/logout")
async def admin_logout(request: Request):
    token = request.cookies.get("wp_session")
    if token:
        conn = get_db()
        conn.execute("DELETE FROM admin_sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    response = JSONResponse({"status": "ok"})
    response.delete_cookie("wp_session")
    return response


@app.get("/v1/auth/me")
async def auth_me(request: Request):
    admin = get_session_admin(request)
    if not admin:
        raise HTTPException(401, "Not authenticated")
    return {"email": admin, "authenticated": True}


@app.post("/v1/entry")
async def register_entry(req: EntryRequest):
    conn = get_db()
    space = conn.execute("SELECT * FROM spaces WHERE space_number=?", (req.space_number,)).fetchone()
    if not space:
        conn.close()
        raise HTTPException(400, "Invalid space number")
    if space["is_occupied"]:
        conn.close()
        raise HTTPException(400, f"Space #{req.space_number} is already occupied")
    existing = conn.execute(
        "SELECT * FROM spaces WHERE plate_number=? AND is_occupied=1", (req.plate_number.upper(),)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(400, f"Vehicle {req.plate_number.upper()} is already parked in space #{existing['space_number']}")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE spaces SET is_occupied=1, plate_number=?, driver_phone=?, driver_email=?, entry_time=? WHERE space_number=?",
        (req.plate_number.upper(), req.driver_phone, req.driver_email, now, req.space_number),
    )
    conn.commit()
    conn.close()
    asyncio.create_task(send_entry_notification_admin(
        req.plate_number.upper(), req.driver_phone, req.driver_email, req.space_number, now
    ))
    if req.driver_email:
        asyncio.create_task(send_driver_entry_notification(
            req.plate_number.upper(), req.driver_phone, req.driver_email, req.space_number, now
        ))
    return {"status": "ok", "plate": req.plate_number.upper(), "space": req.space_number, "entry_time": now}


@app.post("/v1/exit/lookup")
async def exit_lookup(req: ExitLookupRequest):
    conn = get_db()
    space = conn.execute(
        "SELECT * FROM spaces WHERE plate_number=? AND is_occupied=1", (req.plate_number.upper(),)
    ).fetchone()
    conn.close()
    if not space:
        raise HTTPException(404, "Vehicle not found in parking")
    entry_time = datetime.fromisoformat(space["entry_time"])
    now = datetime.now(timezone.utc)
    duration_minutes = (now - entry_time).total_seconds() / 60
    if duration_minutes <= GRACE_MINUTES:
        amount = 0
    else:
        hours = math.ceil(duration_minutes / 60)
        amount = hours * HOURLY_RATE
    return {
        "plate": space["plate_number"],
        "space_number": space["space_number"],
        "driver_phone": space["driver_phone"],
        "driver_email": space["driver_email"],
        "entry_time": space["entry_time"],
        "duration_minutes": round(duration_minutes, 1),
        "amount": amount,
    }


@app.post("/v1/exit/initiate-payment")
async def initiate_payment(req: PaymentInitRequest):
    conn = get_db()
    space = conn.execute(
        "SELECT * FROM spaces WHERE plate_number=? AND is_occupied=1", (req.plate_number.upper(),)
    ).fetchone()
    if not space:
        conn.close()
        raise HTTPException(404, "Vehicle not found")
    entry_time = datetime.fromisoformat(space["entry_time"])
    now = datetime.now(timezone.utc)
    exit_time = now.isoformat()
    duration_minutes = (now - entry_time).total_seconds() / 60
    if duration_minutes <= GRACE_MINUTES:
        conn.execute(
            "UPDATE spaces SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL WHERE space_number=?",
            (space["space_number"],),
        )
        ref = f"FREE-{uuid.uuid4().hex[:8].upper()}"
        conn.execute(
            "INSERT INTO transactions (plate_number,driver_phone,driver_email,space_number,entry_time,exit_time,duration_minutes,amount,transaction_ref,payment_status,gate_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (space["plate_number"], space["driver_phone"], space["driver_email"],
             space["space_number"], space["entry_time"], exit_time,
             duration_minutes, 0, ref, "COMPLETED", "OPEN"),
        )
        conn.commit()
        conn.close()
        return {"status": "free_exit", "gate": "OPEN", "amount": 0, "ref": ref}
    hours = math.ceil(duration_minutes / 60)
    amount = hours * HOURLY_RATE
    ref = f"WP-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        "INSERT INTO transactions (plate_number,driver_phone,driver_email,space_number,entry_time,exit_time,duration_minutes,amount,transaction_ref,payment_status,gate_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (space["plate_number"], space["driver_phone"], space["driver_email"],
         space["space_number"], space["entry_time"], exit_time,
         duration_minutes, amount, ref, "PENDING", "CLOSED"),
    )
    conn.commit()
    invoice_id = None
    stk_error = None
    if INTASEND_API_KEY:
        try:
            phone = space["driver_phone"]
            if phone.startswith("0"):
                phone = "254" + phone[1:]
            elif phone.startswith("+"):
                phone = phone[1:]
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{INTASEND_BASE_URL}/api/v1/payment/mpesa-stk-push/",
                    json={"phone_number": phone, "amount": int(amount),
                          "narrative": f"WellParks Parking - {space['plate_number']}", "api_ref": ref},
                    headers={"Authorization": f"Bearer {INTASEND_API_KEY}", "Content-Type": "application/json"},
                    timeout=30,
                )
                resp_data = resp.json()
                if resp.status_code in (200, 201):
                    invoice_id = resp_data.get("invoice", {}).get("invoice_id") or resp_data.get("id")
                    conn2 = get_db()
                    conn2.execute("UPDATE transactions SET intasend_invoice_id=? WHERE transaction_ref=?",
                                  (str(invoice_id), ref))
                    conn2.commit()
                    conn2.close()
                else:
                    stk_error = resp_data
        except Exception as e:
            stk_error = str(e)
    conn.close()
    result = {"status": "stk_pushed", "ref": ref, "amount": amount,
              "phone": space["driver_phone"], "plate": space["plate_number"]}
    if invoice_id:
        result["invoice_id"] = str(invoice_id)
    if stk_error:
        result["stk_error"] = str(stk_error)
    return result


@app.post("/v1/webhook/intasend")
async def intasend_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    invoice_id = body.get("invoice_id") or body.get("invoice", {}).get("invoice_id")
    state = (body.get("state") or body.get("invoice", {}).get("state", "")).upper()
    mpesa_ref = body.get("mpesa_reference") or body.get("invoice", {}).get("mpesa_reference", "")
    api_ref = body.get("api_ref") or body.get("invoice", {}).get("api_ref", "")
    if state == "COMPLETE":
        conn = get_db()
        txn = None
        if invoice_id:
            txn = conn.execute("SELECT * FROM transactions WHERE intasend_invoice_id=?", (str(invoice_id),)).fetchone()
        if not txn and api_ref:
            txn = conn.execute("SELECT * FROM transactions WHERE transaction_ref=?", (api_ref,)).fetchone()
        if txn and txn["payment_status"] != "COMPLETED":
            final_ref = mpesa_ref or txn["transaction_ref"]
            conn.execute("UPDATE transactions SET payment_status='COMPLETED', gate_status='OPEN', transaction_ref=? WHERE id=?",
                         (final_ref, txn["id"]))
            conn.execute("UPDATE spaces SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL WHERE space_number=?",
                         (txn["space_number"],))
            conn.commit()
            conn.close()
            asyncio.create_task(send_receipt_email(
                txn["driver_email"], txn["plate_number"], txn["entry_time"],
                txn["exit_time"], txn["duration_minutes"], txn["amount"], final_ref,
            ))
        else:
            conn.close()
    return {"status": "ok"}


@app.get("/v1/exit/payment-status/{plate}")
async def payment_status(plate: str):
    conn = get_db()
    txn = conn.execute("SELECT * FROM transactions WHERE plate_number=? ORDER BY id DESC LIMIT 1",
                       (plate.upper(),)).fetchone()
    conn.close()
    if not txn:
        raise HTTPException(404, "No transaction found")
    return {"payment_status": txn["payment_status"], "gate_status": txn["gate_status"],
            "amount": txn["amount"], "ref": txn["transaction_ref"]}


@app.get("/v1/occupancy")
async def public_occupancy():
    conn = get_db()
    occupied = conn.execute("SELECT COUNT(*) FROM spaces WHERE is_occupied=1").fetchone()[0]
    conn.close()
    return {"occupied": occupied, "available": TOTAL_SPACES - occupied, "total": TOTAL_SPACES}


@app.get("/v1/admin/stats")
async def admin_stats(request: Request):
    require_admin(request)
    conn = get_db()
    occupied = conn.execute("SELECT COUNT(*) FROM spaces WHERE is_occupied=1").fetchone()[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    revenue = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE payment_status='COMPLETED' AND date(exit_time)=?",
        (today,)).fetchone()[0]
    exits_today = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE payment_status='COMPLETED' AND date(exit_time)=?",
        (today,)).fetchone()[0]
    total_users = conn.execute(
        "SELECT COUNT(DISTINCT driver_email) FROM ("
        "SELECT driver_email FROM transactions WHERE driver_email IS NOT NULL AND driver_email != '' "
        "UNION "
        "SELECT driver_email FROM spaces WHERE is_occupied=1 AND driver_email IS NOT NULL AND driver_email != ''"
        ")"
    ).fetchone()[0]
    total_revenue = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE payment_status='COMPLETED'"
    ).fetchone()[0]
    conn.close()
    return {"occupied": occupied, "available": TOTAL_SPACES - occupied, "total": TOTAL_SPACES,
            "revenue_today": revenue, "exits_today": exits_today, "total_users": total_users,
            "total_revenue": total_revenue}


@app.get("/v1/admin/recent-exits")
async def recent_exits(request: Request):
    require_admin(request)
    conn = get_db()
    exits = conn.execute(
        "SELECT * FROM transactions WHERE payment_status='COMPLETED' ORDER BY id DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return [dict(e) for e in exits]


@app.get("/v1/admin/monthly-reports")
async def monthly_reports(request: Request):
    require_admin(request)
    conn = get_db()
    reports = conn.execute(
        """
        SELECT 
            strftime('%Y-%m', exit_time) as month,
            COUNT(*) as total_exits,
            COALESCE(SUM(amount), 0) as total_revenue,
            COALESCE(AVG(duration_minutes), 0) as avg_duration,
            COUNT(DISTINCT driver_email) as unique_drivers
        FROM transactions
        WHERE payment_status='COMPLETED' AND exit_time IS NOT NULL
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in reports]


@app.get("/v1/admin/users")
async def list_users(request: Request, search: str = "", status: str = "parked"):
    require_admin(request)
    conn = get_db()
    query = """
        SELECT 
            t.driver_email, t.driver_phone, t.plate_number,
            COUNT(*) as total_visits,
            COALESCE(SUM(t.amount),0) as total_spent,
            MAX(t.created_at) as last_visit
        FROM transactions t
        WHERE t.driver_email IS NOT NULL AND t.driver_email != ''
        GROUP BY t.driver_email, t.plate_number
    """
    rows = conn.execute(query).fetchall()
    parked_spaces = conn.execute(
        "SELECT * FROM spaces WHERE is_occupied=1 AND driver_email IS NOT NULL AND driver_email != ''"
    ).fetchall()
    conn.close()

    users_map = {}
    for row in rows:
        key = (row["driver_email"], row["plate_number"])
        users_map[key] = {
            "driver_email": row["driver_email"],
            "driver_phone": row["driver_phone"],
            "plate_number": row["plate_number"],
            "total_visits": row["total_visits"],
            "total_spent": row["total_spent"],
            "last_visit": row["last_visit"],
            "currently_parked": False,
            "current_space": None,
        }

    for space in parked_spaces:
        key = (space["driver_email"], space["plate_number"])
        entry_time = space["entry_time"]
        if key in users_map:
            users_map[key]["currently_parked"] = True
            users_map[key]["current_space"] = space["space_number"]
            if entry_time and entry_time > (users_map[key]["last_visit"] or ""):
                users_map[key]["last_visit"] = entry_time
        else:
            users_map[key] = {
                "driver_email": space["driver_email"],
                "driver_phone": space["driver_phone"],
                "plate_number": space["plate_number"],
                "total_visits": 1,
                "total_spent": 0,
                "last_visit": entry_time,
                "currently_parked": True,
                "current_space": space["space_number"],
            }

    users = list(users_map.values())
    if search:
        term = search.strip().lower()
        users = [u for u in users if term in (u["driver_email"] or "").lower() or term in (u["plate_number"] or "").lower() or term in (u["driver_phone"] or "").lower()]

    if status == "parked":
        users = [u for u in users if u["currently_parked"]]
    elif status == "exited":
        users = [u for u in users if not u["currently_parked"]]

    users.sort(key=lambda u: u["last_visit"] or "", reverse=True)

    total_unique_drivers = len(users_map)  # Total unique drivers across all
    total_spent = sum(u["total_spent"] for u in users_map.values())

    return {"users": users, "total": total_unique_drivers, "total_spent": total_spent}


@app.delete("/v1/admin/users/{plate}")
async def remove_user(plate: str, request: Request):
    require_admin(request)
    conn = get_db()
    conn.execute("UPDATE spaces SET is_occupied=0, plate_number=NULL, driver_phone=NULL, driver_email=NULL, entry_time=NULL WHERE plate_number=?",
                 (plate.upper(),))
    conn.execute("DELETE FROM transactions WHERE plate_number=?", (plate.upper(),))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": f"All records for {plate.upper()} removed"}


@app.post("/v1/admin/message")
async def send_message(req: MessageRequest, request: Request):
    admin = require_admin(request)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#1a1f36;color:#fff;padding:30px;border-radius:12px;">
        <h2 style="color:#84cc16;">&#128233; Message from WellParks Admin</h2>
        <hr style="border-color:#2d3250;margin:16px 0;">
        <div style="background:#0f1221;border-radius:8px;padding:20px;margin:16px 0;line-height:1.8;color:#e2e8f0;">
            {req.message}
        </div>
        <hr style="border-color:#2d3250;margin:16px 0;">
        <p style="color:#94a3b8;font-size:.8rem;">This message was sent to {req.plate or req.email} by WellParks Admin</p>
    </div>
    """
    await send_email(req.email, req.subject, html)
    log_notification(req.email, req.plate, req.subject, req.message, "ADMIN_MESSAGE")
    return {"status": "ok", "message": f"Message sent to {req.email}"}


@app.post("/v1/admin/broadcast")
async def broadcast(req: BroadcastRequest, request: Request):
    admin = require_admin(request)
    conn = get_db()
    if req.recipient == "all":
        rows = conn.execute(
            "SELECT DISTINCT driver_email, plate_number FROM transactions WHERE driver_email IS NOT NULL AND driver_email != '' AND payment_status='COMPLETED'"
        ).fetchall()
    elif req.recipient == "parked":
        rows = conn.execute(
            "SELECT DISTINCT driver_email, plate_number FROM spaces WHERE is_occupied=1 AND driver_email IS NOT NULL AND driver_email != ''"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT driver_email, plate_number FROM transactions WHERE driver_email=? LIMIT 1", (req.recipient,)
        ).fetchall()
    conn.close()
    count = 0
    seen = set()
    for row in rows:
        email = row["driver_email"]
        if email in seen:
            continue
        seen.add(email)
        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;background:#1a1f36;color:#fff;padding:30px;border-radius:12px;">
            <h2 style="color:#84cc16;">&#128226; {req.subject}</h2>
            <hr style="border-color:#2d3250;margin:16px 0;">
            <div style="background:#0f1221;border-radius:8px;padding:20px;margin:16px 0;line-height:1.8;color:#e2e8f0;">
                {req.message}
            </div>
            <hr style="border-color:#2d3250;margin:16px 0;">
            <p style="color:#94a3b8;font-size:.8rem;">WellParks Parking Management System</p>
        </div>
        """
        asyncio.create_task(send_email(email, req.subject, html))
        log_notification(email, row["plate_number"], req.subject, req.message, "BROADCAST")
        count += 1
    conn2 = get_db()
    conn2.execute(
        "INSERT INTO broadcasts (subject, message, sent_by, recipient_count) VALUES (?,?,?,?)",
        (req.subject, req.message, admin, count)
    )
    conn2.commit()
    conn2.close()
    return {"status": "ok", "sent_to": count}


@app.get("/v1/admin/notifications")
async def get_notifications(request: Request, limit: int = 50):
    require_admin(request)
    conn = get_db()
    notifs = conn.execute(
        "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(n) for n in notifs]


@app.get("/v1/admin/broadcasts")
async def get_broadcasts(request: Request):
    require_admin(request)
    conn = get_db()
    rows = conn.execute("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 20").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/v1/spaces")
async def get_spaces():
    conn = get_db()
    spaces = conn.execute(
        "SELECT space_number, is_occupied, plate_number, entry_time FROM spaces ORDER BY space_number"
    ).fetchall()
    conn.close()
    return [dict(s) for s in spaces]


@app.get("/v1/spaces/{space_number}")
async def get_space(space_number: int):
    conn = get_db()
    space = conn.execute("SELECT * FROM spaces WHERE space_number=?", (space_number,)).fetchone()
    conn.close()
    if not space:
        raise HTTPException(404, "Space not found")
    return dict(space)


@app.get("/login")
async def login_page():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/entry")
async def entry_page():
    return FileResponse(os.path.join(STATIC_DIR, "entry.html"))


@app.get("/exit")
async def exit_page():
    return FileResponse(os.path.join(STATIC_DIR, "exit.html"))


@app.get("/admin")
async def admin_page(request: Request):
    admin = get_session_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


@app.get("/users")
async def users_page(request: Request):
    admin = get_session_admin(request)
    if not admin:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "users.html"))


@app.get("/map")
async def map_page():
    return FileResponse(os.path.join(STATIC_DIR, "map.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
