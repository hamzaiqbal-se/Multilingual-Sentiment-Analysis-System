from app import app
from models import db, User

with app.app_context():
    # Admin User
    admin = User(full_name="Hamza Iqbal", email="hamzaiqbal4748@gmail.com", is_admin=True)
    admin.set_password("admin123") # 
    db.session.add(admin)
    db.session.commit()
    print("Database Seeded: Admin 'Hamza Iqbal' created successfully!")