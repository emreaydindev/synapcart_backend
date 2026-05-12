from sqlalchemy import Column, Integer, String, ForeignKey, Float
from sqlalchemy.orm import relationship
from app.core.database import Base

class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    price = Column(Float)
    source = Column(String)
    link = Column(String)
    thumbnail = Column(String)
    
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="favorites")