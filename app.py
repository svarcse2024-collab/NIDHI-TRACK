"""AICTE Security Deposit / FDR Portal - prototype backend (Flask + SQLite)."""
import csv
import io
import json
import os
import sqlite3
import uuid
from datetime import date, datetime
from functools import wraps

from flask import (Flask, Response, g, jsonify, request, send_from_directory,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("FDR_DB", os.path.join(BASE, "fdr.db"))
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

ALERT_DAYS = 90
ALLOWED_EXT = {"pdf", "png", "jpg", "jpeg"}

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB uploads

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutes(
  id INTEGER PRIMARY KEY, aicte_id TEXT UNIQUE, name TEXT, state TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
  role TEXT, name TEXT, institute_id INTEGER);
CREATE TABLE IF NOT EXISTS fdrs(
  id INTEGER PRIMARY KEY, institute_id INTEGER, fdr_number TEXT UNIQUE,
  bank TEXT, branch TEXT, amount REAL, interest_rate REAL,
  issue_date TEXT, maturity_date TEXT, purpose TEXT, status TEXT,
  document TEXT, remarks TEXT, reviewed_by TEXT,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY, fdr_id INTEGER, type TEXT, status TEXT,
  payload TEXT, note TEXT, decision_remarks TEXT,
  created_at TEXT, decided_at TEXT, decided_by TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, fdr_id INTEGER, actor TEXT, action TEXT,
  detail TEXT, at TEXT);
"""


# ---------- helpers ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(fdr_id, action, detail=""):
    db().execute(
        "INSERT INTO audit(fdr_id,actor,action,detail,at) VALUES(?,?,?,?,?)",
        (fdr_id, session.get("name", "system"), action, detail, now()))


def err(msg, code=400):
    return jsonify(error=msg), code


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrap(*a, **kw):
            if "uid" not in session:
                return err("Login required", 401)
            if role and session["role"] != role:
                return err("Not permitted for your role", 403)
            return fn(*a, **kw)
        return wrap
    return deco


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def fdr_dict(r):
    d = dict(r)
    mat = parse_date(d["maturity_date"])
    days = (mat - date.today()).days if mat else None
    d["days_to_maturity"] = days
    d["alert"] = None
    if d["status"] in ("Verified", "Release Requested") and days is not None:
        if days < 0:
            d["alert"] = "Expired"
        elif days <= ALERT_DAYS:
            d["alert"] = "Expiring soon"
    d["has_document"] = bool(d.get("document"))
    d.pop("document", None)
    return d


def can_access(fdr_row):
    return session["role"] == "officer" or fdr_row["institute_id"] == session["institute_id"]


def get_fdr(fid):
    row = db().execute(
        "SELECT f.*, i.name AS institute_name, i.aicte_id, i.state "
        "FROM fdrs f JOIN institutes i ON i.id=f.institute_id WHERE f.id=?",
        (fid,)).fetchone()
    return row


BASE_SELECT = ("SELECT f.*, i.name AS institute_name, i.aicte_id, i.state "
               "FROM fdrs f JOIN institutes i ON i.id=f.institute_id")


# ---------- auth ----------
@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    u = db().execute("SELECT * FROM users WHERE username=?",
                     (data.get("username", ""),)).fetchone()
    if not u or not check_password_hash(u["password_hash"], data.get("password", "")):
        return err("Invalid username or password", 401)
    session.clear()
    session.update(uid=u["id"], role=u["role"], name=u["name"],
                   institute_id=u["institute_id"])
    return jsonify(me())


def me():
    return {"name": session["name"], "role": session["role"],
            "institute_id": session["institute_id"]}


@app.get("/api/me")
@login_required()
def whoami():
    return jsonify(me())


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------- FDR CRUD ----------
@app.get("/api/fdrs")
@login_required()
def list_fdrs():
    sql, args = BASE_SELECT + " WHERE 1=1", []
    if session["role"] == "institute":
        sql += " AND f.institute_id=?"
        args.append(session["institute_id"])
    status = request.args.get("status")
    if status:
        sql += " AND f.status=?"
        args.append(status)
    q = request.args.get("q", "").strip()
    if q:
        sql += " AND (f.fdr_number LIKE ? OR i.name LIKE ? OR i.aicte_id LIKE ? OR f.bank LIKE ?)"
        args += [f"%{q}%"] * 4
    sql += " ORDER BY f.updated_at DESC"
    rows = [fdr_dict(r) for r in db().execute(sql, args)]
    if request.args.get("alerts") == "1":
        rows = [r for r in rows if r["alert"]]
    return jsonify(rows)


@app.post("/api/fdrs")
@login_required("institute")
def create_fdr():
    f = request.form
    required = ["fdr_number", "bank", "branch", "amount", "interest_rate",
                "issue_date", "maturity_date"]
    missing = [k for k in required if not f.get(k, "").strip()]
    if missing:
        return err("Missing fields: " + ", ".join(missing))
    try:
        amount, rate = float(f["amount"]), float(f["interest_rate"])
    except ValueError:
        return err("Amount and interest rate must be numbers")
    if amount <= 0 or not (0 < rate < 20):
        return err("Amount must be > 0 and interest rate between 0 and 20")
    issue, mat = parse_date(f["issue_date"]), parse_date(f["maturity_date"])
    if not issue or not mat:
        return err("Dates must be YYYY-MM-DD")
    if mat <= issue:
        return err("Maturity date must be after issue date")
    if mat <= date.today():
        return err("FDR has already matured; submit a valid FDR")
    if db().execute("SELECT 1 FROM fdrs WHERE fdr_number=?",
                    (f["fdr_number"].strip(),)).fetchone():
        return err("This FDR number is already registered", 409)

    fname = None
    file = request.files.get("document")
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXT:
            return err("Document must be PDF, PNG or JPG")
        fname = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(UPLOADS, fname))
    else:
        return err("Scanned FDR document is required")

    ts = now()
    cur = db().execute(
        "INSERT INTO fdrs(institute_id,fdr_number,bank,branch,amount,interest_rate,"
        "issue_date,maturity_date,purpose,status,document,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (session["institute_id"], f["fdr_number"].strip(), f["bank"].strip(),
         f["branch"].strip(), amount, rate, f["issue_date"], f["maturity_date"],
         f.get("purpose", "Security deposit").strip(), "Submitted", fname, ts, ts))
    log(cur.lastrowid, "Submitted", f"FDR {f['fdr_number']} for Rs {amount:,.0f}")
    db().commit()
    return jsonify(id=cur.lastrowid), 201


@app.get("/api/fdrs/<int:fid>")
@login_required()
def fdr_detail(fid):
    row = get_fdr(fid)
    if not row or not can_access(row):
        return err("FDR not found", 404)
    d = fdr_dict(row)
    d["audit"] = [dict(a) for a in db().execute(
        "SELECT actor,action,detail,at FROM audit WHERE fdr_id=? ORDER BY id DESC", (fid,))]
    reqs = []
    for r in db().execute("SELECT * FROM requests WHERE fdr_id=? ORDER BY id DESC", (fid,)):
        x = dict(r)
        x["payload"] = json.loads(x["payload"] or "{}")
        reqs.append(x)
    d["requests"] = reqs
    return jsonify(d)


@app.get("/files/<int:fid>")
@login_required()
def get_file(fid):
    row = get_fdr(fid)
    if not row or not can_access(row):
        return err("Not found", 404)
    return send_from_directory(UPLOADS, row["document"])


# ---------- officer workflow ----------
@app.post("/api/fdrs/<int:fid>/review")
@login_required("officer")
def review(fid):
    row = get_fdr(fid)
    if not row:
        return err("FDR not found", 404)
    if row["status"] != "Submitted":
        return err(f"Only 'Submitted' FDRs can be reviewed (current: {row['status']})", 409)
    data = request.get_json(silent=True) or {}
    decision, remarks = data.get("decision"), (data.get("remarks") or "").strip()
    if decision not in ("approve", "reject"):
        return err("decision must be approve or reject")
    if decision == "reject" and not remarks:
        return err("Remarks are required when rejecting")
    status = "Verified" if decision == "approve" else "Rejected"
    db().execute("UPDATE fdrs SET status=?, remarks=?, reviewed_by=?, updated_at=? WHERE id=?",
                 (status, remarks, session["name"], now(), fid))
    log(fid, status, remarks)
    db().commit()
    return jsonify(status=status)


# ---------- institute requests (renewal / release) ----------
@app.post("/api/fdrs/<int:fid>/request")
@login_required("institute")
def raise_request(fid):
    row = get_fdr(fid)
    if not row or not can_access(row):
        return err("FDR not found", 404)
    if row["status"] != "Verified":
        return err("Requests can only be raised on Verified FDRs", 409)
    if db().execute("SELECT 1 FROM requests WHERE fdr_id=? AND status='Pending'", (fid,)).fetchone():
        return err("A request is already pending for this FDR", 409)
    data = request.get_json(silent=True) or {}
    rtype = data.get("type")
    payload = {}
    if rtype == "Renewal":
        new_no = (data.get("new_fdr_number") or "").strip()
        new_mat = parse_date(data.get("new_maturity_date"))
        if not new_no or not new_mat:
            return err("New FDR number and new maturity date are required")
        if new_mat <= parse_date(row["maturity_date"]):
            return err("New maturity date must be later than current maturity")
        if db().execute("SELECT 1 FROM fdrs WHERE fdr_number=?", (new_no,)).fetchone():
            return err("New FDR number is already registered", 409)
        payload = {"new_fdr_number": new_no, "new_maturity_date": data["new_maturity_date"]}
    elif rtype == "Release":
        if not (data.get("note") or "").strip():
            return err("Please give a reason for release")
    else:
        return err("type must be Renewal or Release")
    db().execute(
        "INSERT INTO requests(fdr_id,type,status,payload,note,created_at) VALUES(?,?,?,?,?,?)",
        (fid, rtype, "Pending", json.dumps(payload), data.get("note", ""), now()))
    if rtype == "Release":
        db().execute("UPDATE fdrs SET status='Release Requested', updated_at=? WHERE id=?", (now(), fid))
    log(fid, f"{rtype} requested", data.get("note", ""))
    db().commit()
    return jsonify(ok=True), 201


@app.get("/api/requests")
@login_required("officer")
def pending_requests():
    rows = db().execute(
        "SELECT r.*, f.fdr_number, f.amount, i.name AS institute_name FROM requests r "
        "JOIN fdrs f ON f.id=r.fdr_id JOIN institutes i ON i.id=f.institute_id "
        "WHERE r.status='Pending' ORDER BY r.id").fetchall()
    out = []
    for r in rows:
        x = dict(r)
        x["payload"] = json.loads(x["payload"] or "{}")
        out.append(x)
    return jsonify(out)


@app.post("/api/requests/<int:rid>/decide")
@login_required("officer")
def decide(rid):
    r = db().execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    if not r:
        return err("Request not found", 404)
    if r["status"] != "Pending":
        return err("Request already decided", 409)
    data = request.get_json(silent=True) or {}
    decision, remarks = data.get("decision"), (data.get("remarks") or "").strip()
    if decision not in ("approve", "reject"):
        return err("decision must be approve or reject")
    if decision == "reject" and not remarks:
        return err("Remarks are required when rejecting")
    fid, payload = r["fdr_id"], json.loads(r["payload"] or "{}")
    status = "Approved" if decision == "approve" else "Rejected"
    db().execute("UPDATE requests SET status=?, decision_remarks=?, decided_at=?, decided_by=? WHERE id=?",
                 (status, remarks, now(), session["name"], rid))
    if r["type"] == "Renewal" and decision == "approve":
        db().execute("UPDATE fdrs SET fdr_number=?, maturity_date=?, updated_at=? WHERE id=?",
                     (payload["new_fdr_number"], payload["new_maturity_date"], now(), fid))
    elif r["type"] == "Release":
        new_status = "Released" if decision == "approve" else "Verified"
        db().execute("UPDATE fdrs SET status=?, updated_at=? WHERE id=?", (new_status, now(), fid))
    log(fid, f"{r['type']} {status}", remarks)
    db().commit()
    return jsonify(status=status)


# ---------- dashboard / export ----------
@app.get("/api/stats")
@login_required()
def stats():
    rows = [fdr_dict(r) for r in db().execute(
        BASE_SELECT + (" WHERE f.institute_id=?" if session["role"] == "institute" else ""),
        (session["institute_id"],) if session["role"] == "institute" else ())]
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    held = sum(r["amount"] for r in rows if r["status"] in ("Verified", "Release Requested"))
    pending_req = db().execute("SELECT COUNT(*) FROM requests WHERE status='Pending'").fetchone()[0] \
        if session["role"] == "officer" else None
    return jsonify(total=len(rows), by_status=by_status, amount_held=held,
                   alerts=sum(1 for r in rows if r["alert"]), pending_requests=pending_req)


@app.get("/api/export.csv")
@login_required("officer")
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["AICTE ID", "Institute", "State", "FDR No", "Bank", "Branch", "Amount",
                "Rate %", "Issue", "Maturity", "Days left", "Status", "Alert"])
    for r in db().execute(BASE_SELECT + " ORDER BY i.name"):
        d = fdr_dict(r)
        w.writerow([d["aicte_id"], d["institute_name"], d["state"], d["fdr_number"], d["bank"],
                    d["branch"], d["amount"], d["interest_rate"], d["issue_date"],
                    d["maturity_date"], d["days_to_maturity"], d["status"], d["alert"] or ""])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=fdr_report.csv"})


@app.get("/")
def index():
    return app.send_static_file("index.html")


# ---------- init + demo data ----------
def init_db(seed=True):
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    if seed and not conn.execute("SELECT 1 FROM users").fetchone():
        insts = [("1-100234", "RMD Engineering College", "Tamil Nadu", "admin@rmd.example"),
                 ("1-100871", "Sample Institute of Technology", "Karnataka", "office@sit.example")]
        for i in insts:
            conn.execute("INSERT INTO institutes(aicte_id,name,state,email) VALUES(?,?,?,?)", i)
        users = [("officer", "officer123", "officer", "AICTE Officer (Finance)", None),
                 ("rmd", "rmd123", "institute", "RMD Admin", 1),
                 ("sit", "sit123", "institute", "SIT Admin", 2)]
        for u, p, role, name, inst in users:
            conn.execute("INSERT INTO users(username,password_hash,role,name,institute_id) VALUES(?,?,?,?,?)",
                         (u, generate_password_hash(p), role, name, inst))
        from datetime import timedelta
        t = date.today()
        demo = [(1, "FDR-SBI-0001", "State Bank of India", "Chennai Main", 500000, 6.8,
                 t - timedelta(days=300), t + timedelta(days=45), "Verified"),
                (1, "FDR-SBI-0002", "State Bank of India", "Chennai Main", 750000, 7.0,
                 t - timedelta(days=100), t + timedelta(days=265), "Submitted"),
                (2, "FDR-CAN-0101", "Canara Bank", "Bengaluru Jayanagar", 1000000, 6.9,
                 t - timedelta(days=700), t + timedelta(days=20), "Verified")]
        ts = now()
        for n, (inst, no, bank, br, amt, rate, iss, mat, st) in enumerate(demo, 1):
            conn.execute(
                "INSERT INTO fdrs(institute_id,fdr_number,bank,branch,amount,interest_rate,issue_date,"
                "maturity_date,purpose,status,document,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inst, no, bank, br, amt, rate, iss.isoformat(), mat.isoformat(),
                 "Security deposit", st, "demo.pdf", ts, ts))
            conn.execute("INSERT INTO audit(fdr_id,actor,action,detail,at) VALUES(?,?,?,?,?)",
                         (n, "system", "Seeded", "Demo record", ts))
        demo_pdf = os.path.join(UPLOADS, "demo.pdf")
        if not os.path.exists(demo_pdf):
            with open(demo_pdf, "wb") as fh:
                fh.write(b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                         b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                         b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 100]>>endobj\n"
                         b"trailer<</Root 1 0 R>>\n%%EOF")
    conn.commit()
    conn.close()


init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
