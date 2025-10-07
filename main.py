# main.py
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import datetime
import models
from models import Email, ParsedItem, get_engine, create_db, SessionLocal
from email_fetcher import connect_imap, fetch_recent_messages, extract_text_from_message, load_eml_file
from parser import parse_email_text
from sqlalchemy.orm import Session
import uvicorn
import json

app = FastAPI(title="Email Query MVP")

engine = get_engine()
create_db(engine)

class IMAPCreds(BaseModel):
    host: str
    username: str
    password: str
    folder: Optional[str] = "INBOX"
    limit: Optional[int] = 50

def save_email_and_items(db: Session, message_id: str, meta: dict, raw_bytes: bytes, parsed_items: list):
    # avoid duplicate by message_id
    existing = db.query(Email).filter(Email.message_id == message_id).first()
    if existing:
        return existing
    e = Email(
        message_id=message_id,
        subject=meta.get("subject"),
        sender=meta.get("from"),
        to=meta.get("to"),
        date_received=datetime.datetime.utcnow(), # ideally parse Date header
        body=meta.get("text"),
        raw=raw_bytes.decode(errors='ignore') if raw_bytes else None
    )
    db.add(e)
    db.flush()
    for it in parsed_items:
        p = ParsedItem(
            email_id=e.id,
            item_type=it.get("item_type"),
            subtype=it.get("subtype"),
            amount=it.get("amount"),
            currency=it.get("currency"),
            date=it.get("date"),
            confidence=it.get("confidence"),
            summary=it.get("summary")
        )
        db.add(p)
    db.commit()
    db.refresh(e)
    return e

@app.post("/fetch")
def fetch_emails(creds: IMAPCreds):
    """Fetch mails from IMAP immediately and parse them. Returns count parsed."""
    try:
        M = connect_imap(creds.host, creds.username, creds.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"IMAP connection failed: {e}")
    msgs = fetch_recent_messages(M, folder=creds.folder, limit=creds.limit)
    db = SessionLocal()
    count = 0
    for mid, msg, raw in msgs:
        meta = extract_text_from_message(msg)
        parsed = parse_email_text(meta.get("text") or "")
        save_email_and_items(db, mid, meta, raw, parsed)
        count += 1
    return {"fetched": count}

@app.post("/upload-eml")
def upload_eml(file: UploadFile = File(...)):
    content = file.file.read()
    import email
    msg = email.message_from_bytes(content)
    meta = extract_text_from_message(msg)
    parsed = parse_email_text(meta.get("text") or "")
    db = SessionLocal()
    saved = save_email_and_items(db, meta.get("subject") or file.filename, meta, content, parsed)
    return {"status": "ok", "email_id": saved.id}

@app.get("/contracts/expiring")
def contracts_expiring(days: int = 90):
    db = SessionLocal()
    cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=days)
    items = db.query(ParsedItem).filter(ParsedItem.item_type == 'contract', ParsedItem.date != None, ParsedItem.date <= cutoff).all()
    out = []
    for i in items:
        out.append({
            "id": i.id,
            "email_id": i.email_id,
            "summary": i.summary,
            "expires_on": i.date.isoformat() if i.date else None,
            "confidence": i.confidence
        })
    return {"count": len(out), "contracts": out}

@app.get("/bills/upcoming")
def bills_upcoming(days: int = 30):
    db = SessionLocal()
    cutoff = datetime.datetime.utcnow() + datetime.timedelta(days=days)
    items = db.query(ParsedItem).filter(ParsedItem.item_type.in_(('invoice', 'bill')), ParsedItem.date != None, ParsedItem.date <= cutoff).all()
    s = []
    for i in items:
        s.append({
            "id": i.id,
            "email_id": i.email_id,
            "amount": i.amount,
            "currency": i.currency,
            "due_date": i.date.isoformat() if i.date else None,
            "summary": i.summary,
            "confidence": i.confidence
        })
    total = sum(i['amount'] for i in s if i['amount'])
    return {"count": len(s), "total_estimated": total, "items": s}

@app.get("/emails/{email_id}")
def get_email(email_id: int):
    db = SessionLocal()
    e = db.query(Email).filter(Email.id == email_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="email not found")
    items = [{
        "id": it.id,
        "type": it.item_type,
        "amount": it.amount,
        "currency": it.currency,
        "date": it.date.isoformat() if it.date else None,
        "summary": it.summary
    } for it in e.parsed_items]
    return {
        "id": e.id,
        "subject": e.subject,
        "from": e.sender,
        "to": e.to,
        "body": e.body[:3000],
        "parsed_items": items
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
