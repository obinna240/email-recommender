# parser.py
import re
from dateparser import parse as dp_parse
from datetime import datetime
import math

MONEY_RE = re.compile(
    r'(?P<symbol>£|\$|€)?\s?(?P<amount>[0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?)\s?(?P<ccy>GBP|USD|EUR|£|\$|€)?',
    flags=re.IGNORECASE
)

# Simple heuristics for classification
def classify_text(text: str):
    txt = text.lower()
    if "invoice" in txt or "amount due" in txt or "invoice number" in txt:
        return "invoice"
    if "contract" in txt or "agreement" in txt or "expires" in txt or "expiration" in txt:
        return "contract"
    if "due date" in txt and ("utility" in txt or "bill" in txt):
        return "bill"
    # fallback
    return "other"

def extract_money_candidates(text: str):
    results = []
    for m in MONEY_RE.finditer(text):
        amt = m.group("amount")
        sym = m.group("symbol") or m.group("ccy") or ""
        # normalize amount: replace thousands separators and convert comma decimal
        norm = amt.replace(",", "") if amt.count(",") > amt.count(".") else amt.replace(",", "")
        # try float
        try:
            value = float(norm)
        except Exception:
            # last resort: replace periods except last
            s = re.sub(r'(?<=\d)\.(?=\d{3}\b)', '', amt)
            s = s.replace(",", ".")
            try:
                value = float(s)
            except Exception:
                continue
        currency = None
        if sym.strip() in ("£", "GBP"):
            currency = "GBP"
        elif sym.strip() in ("$", "USD"):
            currency = "USD"
        elif sym.strip() in ("€", "EUR"):
            currency = "EUR"
        results.append({"value": value, "currency": currency, "raw": m.group(0)})
    return results

def extract_dates(text: str, ref=None):
    # returns list of (datetime, raw_text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    res = []
    for line in lines:
        # quick filter: if line contains words like 'due', 'expires', 'expiry', 'renewal', 'date', or looks like a date
        if any(k in line.lower() for k in ("due", "due date", "expires", "expiry", "effective", "end date", "renewal", "term", "period", "invoice date")) or re.search(r'\b\d{1,2}[\/\-\.\s]\d{1,2}[\/\-\.\s]\d{2,4}\b', line):
            d = dp_parse(line, settings={'PREFER_DAY_OF_MONTH': 'first', 'RELATIVE_BASE': ref} if ref else None)
            if d:
                res.append({"dt": d, "raw": line})
    # fallback: try parsing anywhere
    if not res:
        for line in lines[:100]:
            d = dp_parse(line, settings={'PREFER_DAY_OF_MONTH': 'first', 'RELATIVE_BASE': ref} if ref else None)
            if d:
                res.append({"dt": d, "raw": line})
    return res

def parse_email_text(text: str, email_meta=None):
    """
    Returns list of parsed items with item_type, amount, currency, date, summary, confidence
    """
    items = []
    item_type = classify_text(text)
    monies = extract_money_candidates(text)
    dates = extract_dates(text, ref=datetime.utcnow())
    # heuristics: create candidates
    if item_type in ("invoice", "bill"):
        for m in monies:
            # try to pair with nearest date if present
            dt = dates[0]['dt'] if dates else None
            summary = f"{item_type} detected: {m['raw']}" + (f"; date: {dt.date()}" if dt else "")
            items.append({
                "item_type": item_type,
                "subtype": None,
                "amount": m['value'],
                "currency": m['currency'],
                "date": dt,
                "confidence": 0.8,
                "summary": summary
            })
        # if no money found but dates found, record a bill with no amount
        if not monies and dates:
            items.append({
                "item_type": item_type,
                "subtype": None,
                "amount": None,
                "currency": None,
                "date": dates[0]['dt'],
                "confidence": 0.6,
                "summary": f"{item_type} detected, date {dates[0]['raw']}"
            })
    elif item_type == "contract":
        # try to find an end date / expiration
        if dates:
            # pick latest date mentioned as likely expiry
            latest = max(d['dt'] for d in dates)
            items.append({
                "item_type": "contract",
                "subtype": None,
                "amount": None,
                "currency": None,
                "date": latest,
                "confidence": 0.85,
                "summary": f"Contract expiry/term date: {latest.date()}"
            })
    else:
        # try to capture any money/date mentions
        if monies:
            for m in monies:
                items.append({
                    "item_type": "other",
                    "subtype": None,
                    "amount": m['value'],
                    "currency": m['currency'],
                    "date": dates[0]['dt'] if dates else None,
                    "confidence": 0.5,
                    "summary": f"Money mention: {m['raw']}"
                })
    return items
