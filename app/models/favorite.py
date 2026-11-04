from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base, utcnow


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "link", name="uq_favorites_user_link"),)

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    price = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    source = Column(String)
    link = Column(String)
    thumbnail = Column(String)
    created_at = Column(DateTime, nullable=True, default=utcnow)

    # Price alerts (premium): notify when the price drops to `target_price`.
    target_price = Column(Float, nullable=True)
    last_checked_price = Column(Float, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    # Price of the last alert sent, so a stable price doesn't notify every day.
    last_notified_price = Column(Float, nullable=True)

    user_id = Column(String, ForeignKey("users.id"), index=True)
    owner = relationship("User", back_populates="favorites")
