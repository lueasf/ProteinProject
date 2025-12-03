"""
Module pour supprimer une protéine de MongoDB et Neo4j.
- MongoDB: supprime le document de la protéine
- Neo4j: supprime le nœud protéine ET toutes ses relations SIMILAR
"""

from pymongo import MongoClient
from neo4j import GraphDatabase
import os
import dotenv

dotenv.load_dotenv()

# Configuration MongoDB
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

# Configuration Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE_NAME", "project")


def delete_protein_from_mongo(entry_id):
    """
    Supprime une protéine de la base de données MongoDB.
    """
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        result = collection.delete_one({"_id": entry_id})
        
        if result.deleted_count > 0:
            print(f"✅ Protéine {entry_id} supprimée de MongoDB")
            client.close()
            return True
        else:
            print(f"ℹ️ Protéine {entry_id} non trouvée dans MongoDB")
            client.close()
            return False
            
    except Exception as e:
        print(f"❌ Erreur MongoDB: {e}")
        return False


def delete_protein_from_neo4j(entry_id):
    """
    Supprime une protéine de Neo4j ainsi que toutes ses relations SIMILAR.
    """
    driver = None
    result = {
        "node_deleted": False,
        "relations_deleted": 0
    }
    
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        with driver.session(database=NEO4J_DATABASE) as session:
            
            # 1. Compter les relations SIMILAR avant suppression
            def count_relations(tx):
                res = tx.run(
                    """
                    MATCH (p:Protein {entry: $entry})-[r:SIMILAR]-()
                    RETURN count(r) as count
                    """,
                    entry=entry_id
                )
                record = res.single()
                return record["count"] if record else 0
            
            relations_count = session.execute_read(count_relations)
            
            # 2. Supprimer le nœud et toutes ses relations (DETACH DELETE)
            def delete_node_and_relations(tx):
                res = tx.run(
                    """
                    MATCH (p:Protein {entry: $entry})
                    DETACH DELETE p
                    RETURN count(p) as deleted
                    """,
                    entry=entry_id
                )
                record = res.single()
                return record["deleted"] if record else 0
            
            deleted = session.execute_write(delete_node_and_relations)
            
            if deleted > 0:
                result["node_deleted"] = True
                result["relations_deleted"] = relations_count
                print(f"✅ Protéine {entry_id} supprimée de Neo4j")
                print(f"   └── {relations_count} relation(s) SIMILAR supprimée(s)")
            else:
                print(f"ℹ️ Protéine {entry_id} non trouvée dans Neo4j")
                
    except Exception as e:
        print(f"❌ Erreur Neo4j: {e}")
    finally:
        if driver:
            driver.close()
    
    return result


def delete_protein(entry_id):
    """
    Supprime une protéine de MongoDB et Neo4j (avec toutes ses relations).
    """
    if not entry_id:
        print("❌ L'ID de la protéine (entry) est requis")
        return {"success": False, "error": "Entry ID is required"}
    
    result = {
        "entry": entry_id,
        "mongodb": {"deleted": False},
        "neo4j": {"deleted": False, "relations_deleted": 0}
    }
    
    print(f"\n🗑️ Suppression de la protéine {entry_id}...")
    print("-" * 40)
    
    # 1. Supprimer de MongoDB
    mongo_deleted = delete_protein_from_mongo(entry_id)
    result["mongodb"]["deleted"] = mongo_deleted
    
    # 2. Supprimer de Neo4j (nœud + relations)
    neo4j_result = delete_protein_from_neo4j(entry_id)
    result["neo4j"]["deleted"] = neo4j_result["node_deleted"]
    result["neo4j"]["relations_deleted"] = neo4j_result["relations_deleted"]
    
    # Succès si supprimé d'au moins une base
    result["success"] = result["mongodb"]["deleted"] or result["neo4j"]["deleted"]
    
    print("-" * 40)
    if result["success"]:
        print(f"✅ Suppression terminée pour {entry_id}")
    else:
        print(f"⚠️ Protéine {entry_id} non trouvée dans les bases de données")
    
    return result

# Exemple d'utilisation
if __name__ == "__main__":
    # ID de la protéine à supprimer (exemple)
    protein_id = "P99999"
    
    print("=" * 60)
    print(f"Suppression de la protéine {protein_id}")
    print("=" * 60)
    
    # Supprimer directement
    result = delete_protein(protein_id)
    
    print("\n" + "=" * 60)
    print("Résultat final:")
    print("=" * 60)
    print(f"Entry: {result['entry']}")
    print(f"MongoDB: {'✅ Supprimée' if result['mongodb']['deleted'] else '❌ Non trouvée'}")
    print(f"Neo4j: {'✅ Supprimée' if result['neo4j']['deleted'] else '❌ Non trouvée'}")
    if result['neo4j']['deleted']:
        print(f"Relations SIMILAR supprimées: {result['neo4j']['relations_deleted']}")
