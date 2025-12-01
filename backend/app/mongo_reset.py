import os
import dotenv
from pymongo import MongoClient

dotenv.load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

def reset_database():
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        
        # On supprime direct, sans poser de question
        # Le frontend s'est déjà chargé de demander "Êtes-vous sûr ?"
        if COLLECTION_NAME in db.list_collection_names():
            db[COLLECTION_NAME].drop()
            print(f"✅ Collection '{COLLECTION_NAME}' supprimée avec succès.")
        else:
            print(f"ℹ️  La collection '{COLLECTION_NAME}' n'existait pas.")
            
    except Exception as e:
        print(f"❌ Erreur critique : {e}")

if __name__ == "__main__":
    reset_database()