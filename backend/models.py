"""SQLAlchemy models for PostgreSQL."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, Index
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ReviewResponse(Base):
    __tablename__ = "review_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(50))
    slug = Column(String(255))
    b_name_id = Column(Integer, nullable=True)
    store_id = Column(String(255), nullable=True)
    order_id = Column(String(255), index=True)
    order_timestamp = Column(DateTime, nullable=True)
    review_timestamp = Column(DateTime, nullable=True)
    review_id = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    rating = Column(Integer, nullable=True)
    star_rating = Column(Float, nullable=True)
    review_text = Column(Text, nullable=True)
    items = Column(Text, nullable=True)
    item_reviews = Column(Text, nullable=True)
    response_text = Column(Text, nullable=True)
    response_type = Column(String(50), nullable=True)
    generated_at = Column(DateTime, nullable=True)
    config_id = Column(Integer, nullable=True)
    coupon_value = Column(Float, nullable=True)
    min_order_value = Column(Float, nullable=True)
    response_sent = Column(DateTime, nullable=True)
    errors = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
