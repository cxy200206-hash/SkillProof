import os
from app import DB_PATH, init_db
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
init_db()
print('SkillProof demo database reset:', DB_PATH)
