# models.py
from sqlalchemy import (Column, Integer, String, DateTime, Text, Float, Boolean,
                        ForeignKey, create_engine, func)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import datetime

Base = declarative_base()

class Email(Base):
    __tablename__ = "emails"
    id = Column(Integer, primary_key=True)
    message_id = Column(String, unique=True, index=True)
    subject = Column(String)
    sender = Column(String)
    to = Column(String)
    date_received = Column(DateTime)
    body = Column(Text)
    raw = Column(Text)  # optional raw text
    created_at = Column(DateTime, default=func.now())

    parsed_items = relationship("ParsedItem", back_populates="email")

class ParsedItem(Base):
    __tablename__ = "parsed_items"
    id = Column(Integer, primary_key=True)
    email_id = Column(Integer, ForeignKey("emails.id"))
    item_type = Column(String)   # 'invoice' | 'contract' | 'bill' | 'other'
    subtype = Column(String)     # e.g. 'utility'
    amount = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    date = Column(DateTime, nullable=True)   # due date / end date / invoice date
    confidence = Column(Float, default=0.7)
    summary = Column(Text)
    created_at = Column(DateTime, default=func.now())

    email = relationship("Email", back_populates="parsed_items")


def get_engine(db_url="sqlite:///./emails.db"):
    return create_engine(db_url, connect_args={"check_same_thread": False})

def create_db(engine):
    Base.metadata.create_all(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
