"""Run once to set up your first admin login and a couple of sample games.
Usage: python seed.py
"""
from app.database import Base, engine, SessionLocal
from app.security import hash_password
from app import models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if not db.query(models.User).filter_by(username="admin").first():
    db.add(models.User(
        username="admin",
        hashed_password=hash_password("changeme123"),  # change this immediately after first login
        role=models.UserRole.admin,
    ))
    print("Created admin user -> username: admin / password: changeme123 (change this!)")

if not db.query(models.User).filter_by(username="coder1").first():
    db.add(models.User(
        username="coder1",
        hashed_password=hash_password("changeme123"),
        role=models.UserRole.annotator,
    ))
    print("Created annotator user -> username: coder1 / password: changeme123")

if db.query(models.Game).count() == 0:
    db.add_all([
        models.Game(date="2026-07-22", mf="F", home_team="New York Liberty", visitor_team="Chicago Sky",
                    complete_by="YaminiF", qa_by="akshadamane", is_complete=True, is_qa_done=True, notes="Received"),
        models.Game(date="2026-07-20", mf="M", home_team="Memphis Grizzlies", visitor_team="Golden State Warriors",
                    complete_by="sgawade", qa_by="poojashirsath", is_complete=True, is_qa_done=True, notes="Received"),
    ])
    print("Created 2 sample games")

db.commit()
db.close()
print("Seed complete.")
