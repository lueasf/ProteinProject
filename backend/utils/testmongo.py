from pymongo import MongoClient
import os
import dotenv
import platform

dotenv.load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

print(f"🖥️ Système d'exploitation : {platform.system()}")
print(f"🔍 URI MongoDB : {MONGO_URI}")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    
    # Obtenir des informations sur le serveur MongoDB
    server_info = client.server_info()
    host_info = client.admin.command('hostInfo')
    
    print("\n✅ Connexion réussie")
    print("\n📍 Informations du serveur MongoDB :")
    print(f"   - Version : {server_info['version']}")
    print(f"   - Système : {host_info['os']['name']} {host_info['os']['version']}")
    print(f"   - Hostname : {host_info['system']['hostname']}")
    
    # Vérifier les bases de données
    print("\n📚 Bases de données :")
    for db_name in client.list_database_names():
        db = client[db_name]
        stats = db.command('dbStats')
        print(f"   - {db_name} : {stats['collections']} collections, {stats['dataSize']} bytes")
    
    # Vérifier spécifiquement protein_bank
    if 'protein_bank' in client.list_database_names():
        db = client['protein_bank']
        count = db.proteins.count_documents({})
        print(f"\n✅ Base protein_bank trouvée avec {count} documents")
    else:
        print("\n⚠️ Base protein_bank non trouvée")
    
    client.close()
    
except Exception as e:
    print(f"\n❌ Erreur : {e}")