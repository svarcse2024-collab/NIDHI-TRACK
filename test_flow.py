"""End-to-end smoke test of the whole FDR workflow (uses a throwaway DB)."""
import io
import os
import tempfile

os.environ["FDR_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
import app as portal  # noqa: E402

c = portal.app.test_client()


def login(u, p):
    r = c.post("/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.json
    return r.json


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    assert cond, msg


check(c.post("/api/login", json={"username": "rmd", "password": "bad"}).status_code == 401, "bad login rejected")
check(c.get("/api/fdrs").status_code == 401, "anonymous blocked")

login("rmd", "rmd123")
mine = c.get("/api/fdrs").json
check(len(mine) == 2 and all(r["institute_name"].startswith("RMD") for r in mine), "institute sees only own FDRs")
check(c.get("/api/fdrs/3").status_code == 404, "cannot open another institute's FDR")
check(c.get("/api/export.csv").status_code == 403, "institute cannot export")

form = {"fdr_number": "FDR-NEW-1", "bank": "HDFC", "branch": "T Nagar", "amount": "250000",
        "interest_rate": "7.1", "issue_date": "2026-10-01", "maturity_date": "2027-10-01",
        "document": (io.BytesIO(b"%PDF-1.1 test"), "fdr.pdf")}
r = c.post("/api/fdrs", data=form, content_type="multipart/form-data")
check(r.status_code == 201, "FDR submitted")
fid = r.json["id"]
form["document"] = (io.BytesIO(b"x"), "fdr.pdf")
check(c.post("/api/fdrs", data=form, content_type="multipart/form-data").status_code == 409, "duplicate FDR number blocked")
bad = dict(form, fdr_number="FDR-BAD", maturity_date="2026-09-01", document=(io.BytesIO(b"x"), "a.pdf"))
check(c.post("/api/fdrs", data=bad, content_type="multipart/form-data").status_code == 400, "maturity before issue blocked")
bad = dict(form, fdr_number="FDR-EXE", document=(io.BytesIO(b"x"), "a.exe"))
check(c.post("/api/fdrs", data=bad, content_type="multipart/form-data").status_code == 400, "bad file type blocked")
check(c.post(f"/api/fdrs/{fid}/review", json={"decision": "approve"}).status_code == 403, "institute cannot self-approve")
c.post("/api/logout")

login("officer", "officer123")
check(c.post(f"/api/fdrs/{fid}/review", json={"decision": "reject"}).status_code == 400, "reject needs remarks")
check(c.post(f"/api/fdrs/{fid}/review", json={"decision": "approve", "remarks": "Docs OK"}).json["status"] == "Verified", "officer verifies")
check(c.post(f"/api/fdrs/{fid}/review", json={"decision": "approve"}).status_code == 409, "cannot review twice")
s = c.get("/api/stats").json
check(s["alerts"] == 2, f"maturity alerts counted ({s['alerts']})")
check(len(c.get("/api/fdrs?alerts=1").json) == 2, "alerts filter works")
check(c.get("/api/export.csv").data.count(b"\n") >= 5, "CSV export works")
c.post("/api/logout")

login("rmd", "rmd123")
check(c.get(f"/files/{fid}").status_code == 200, "owner can open document")
r = c.post(f"/api/fdrs/{fid}/request", json={"type": "Renewal", "new_fdr_number": "FDR-NEW-2", "new_maturity_date": "2028-10-01"})
check(r.status_code == 201, "renewal requested")
check(c.post(f"/api/fdrs/{fid}/request", json={"type": "Release", "note": "x"}).status_code == 409, "second pending request blocked")
c.post("/api/logout")

login("officer", "officer123")
rid = c.get("/api/requests").json[0]["id"]
check(c.post(f"/api/requests/{rid}/decide", json={"decision": "approve"}).json["status"] == "Approved", "renewal approved")
d = c.get(f"/api/fdrs/{fid}").json
check(d["fdr_number"] == "FDR-NEW-2" and d["maturity_date"] == "2028-10-01", "FDR updated after renewal")
c.post("/api/logout")

login("rmd", "rmd123")
c.post(f"/api/fdrs/{fid}/request", json={"type": "Release", "note": "Course closed"})
check(c.get(f"/api/fdrs/{fid}").json["status"] == "Release Requested", "status -> Release Requested")
c.post("/api/logout")
login("officer", "officer123")
rid = c.get("/api/requests").json[0]["id"]
c.post(f"/api/requests/{rid}/decide", json={"decision": "approve", "remarks": "NOC issued"})
d = c.get(f"/api/fdrs/{fid}").json
check(d["status"] == "Released", "FDR released")
check(len(d["audit"]) >= 6, f"audit trail recorded ({len(d['audit'])} entries)")
check(c.get("/").status_code == 200, "frontend served")
print("\nALL CHECKS PASSED")
