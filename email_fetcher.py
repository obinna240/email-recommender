# email_fetcher.py
import imaplib
import email
from email.header import decode_header
import base64
import quopri
import os
from typing import List
from pdfminer.high_level import extract_text as pdf_extract_text
from io import BytesIO
from PIL import Image
import pytesseract
import magic

def _decode_mime_words(s):
    parts = decode_header(s)
    out = ""
    for p, enc in parts:
        if isinstance(p, bytes):
            out += p.decode(enc or 'utf-8', errors='ignore')
        else:
            out += p
    return out

def connect_imap(host, username, password, port=993, use_ssl=True):
    if use_ssl:
        M = imaplib.IMAP4_SSL(host, port)
    else:
        M = imaplib.IMAP4(host, port)
    M.login(username, password)
    return M

def fetch_recent_messages(imap_conn, folder="INBOX", limit=50):
    imap_conn.select(folder)
    typ, data = imap_conn.search(None, 'ALL')
    ids = data[0].split()
    # only last N
    selected = ids[-limit:]
    messages = []
    for mid in selected:
        typ, msg_data = imap_conn.fetch(mid, '(RFC822)')
        if typ != 'OK':
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        messages.append((mid.decode(), msg, raw))
    return messages

def extract_text_from_message(msg):
    """
    returns subject, from, to, date, plain_text
    """
    subject = _decode_mime_words(msg.get("Subject") or "")
    sender = _decode_mime_words(msg.get("From") or "")
    to = _decode_mime_words(msg.get("To") or "")
    date = msg.get("Date")
    body_text = []

    for part in msg.walk():
        ctype = part.get_content_type()
        disp = part.get("Content-Disposition")
        if ctype == "text/plain" and disp is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            try:
                text = payload.decode(charset, errors='ignore')
            except:
                text = payload.decode('utf-8', errors='ignore')
            body_text.append(text)
        elif ctype == "text/html" and disp is None and not body_text:
            # fallback: strip HTML quickly
            payload = part.get_payload(decode=True)
            try:
                html = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
            except:
                html = payload.decode('utf-8', errors='ignore')
            # naive strip tags:
            text = re.sub('<[^<]+?>', '', html)
            body_text.append(text)
        elif part.get_content_maintype() == 'multipart':
            continue
        else:
            # attachment: try to extract text for PDFs and images
            filename = part.get_filename()
            if filename:
                payload = part.get_payload(decode=True)
                # use magic to check type
                mtype = magic.from_buffer(payload, mime=True)
                if mtype == 'application/pdf' or (filename.lower().endswith('.pdf')):
                    try:
                        txt = pdf_extract_text(BytesIO(payload))
                        body_text.append("\n\n[attachment: " + (filename or "pdf") + "]\n" + txt)
                    except Exception as e:
                        body_text.append(f"\n\n[attachment pdf {filename} unreadable: {e}]\n")
                elif mtype and mtype.startswith("image/") or any(filename.lower().endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.tiff')):
                    try:
                        img = Image.open(BytesIO(payload))
                        txt = pytesseract.image_to_string(img)
                        body_text.append("\n\n[attachment image: " + filename + "]\n" + txt)
                    except Exception as e:
                        body_text.append(f"\n\n[attachment image {filename} unreadable: {e}]\n")
    return {
        "subject": subject,
        "from": sender,
        "to": to,
        "date": date,
        "text": "\n\n".join(body_text)
    }

# also helper to load .eml files
def load_eml_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    msg = email.message_from_bytes(raw)
    return None, msg, raw
