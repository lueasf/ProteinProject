"""
Module pour ajouter une protéine à MongoDB et Neo4j.
- MongoDB: stocke les informations de la protéine
- Neo4j: crée le nœud protéine et les relations SIMILAR basées sur les domaines InterPro partagés
"""

from pymongo import MongoClient
from neo4j import GraphDatabase
import os
import dotenv
import re
import ast

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


def split_string_to_list(val, delimiter=';'):
    """Fonction pour nettoyer et diviser les chaînes (InterPro, EC)"""
    if val is None or val == '':
        return []
    return [x.strip() for x in str(val).split(delimiter) if x.strip()]


def process_protein_names(val):
    """Fonction pour nettoyer les noms de protéines"""
    if val is None:
        return []
    names = re.split(r'\s*\(', val)
    clean_names = []
    for n in names:
        n = n.replace(')', '').strip()
        if not n.startswith('EC '):
            clean_names.append(n)
    return clean_names


def prepare_mongo_document(protein_data):
    """
    Prépare un document MongoDB à partir des données d'une protéine.
    """
    return {
        "_id": protein_data.get("entry"),
        "entry_name": protein_data.get("entry_name", ""),
        "protein_names": process_protein_names(protein_data.get("protein_names", "")),
        "organism": protein_data.get("organism", ""),
        "sequence": protein_data.get("sequence", ""),
        "sequence_length": len(protein_data.get("sequence", "")),
        "annotations": {
            "ec_numbers": split_string_to_list(protein_data.get("ec_numbers", "")),
            "interpro": split_string_to_list(protein_data.get("interpro", ""))
        }
    }


def add_protein_to_mongo(protein_data):
    """
    Ajoute une protéine à la base de données MongoDB.
    """
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        doc = prepare_mongo_document(protein_data)
        
        # Utiliser upsert pour éviter les doublons
        result = collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True
        )
        
        if result.upserted_id:
            print(f"✅ Protéine {doc['_id']} ajoutée à MongoDB")
        else:
            print(f"🔄 Protéine {doc['_id']} mise à jour dans MongoDB")
        
        client.close()
        return doc["_id"]
        
    except Exception as e:
        print(f"❌ Erreur MongoDB: {e}")
        return None


def add_protein_to_neo4j(protein_data):
    """
    Ajoute une protéine à Neo4j et crée les relations SIMILAR avec les protéines
    partageant des domaines InterPro.
    """
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        # Préparer les données pour Neo4j
        entry = protein_data.get("entry")
        entry_name = protein_data.get("entry_name", "")
        protein_names = process_protein_names(protein_data.get("protein_names", ""))
        organism = protein_data.get("organism", "")
        sequence = protein_data.get("sequence", "")
        ec_numbers = split_string_to_list(protein_data.get("ec_numbers", ""))
        interpro_list = split_string_to_list(protein_data.get("interpro", ""))
        
        relations = []
        similar_count = 0
        
        with driver.session(database=NEO4J_DATABASE) as session:
            # 1. Créer ou mettre à jour le nœud de la protéine
            def create_protein_node(tx):
                tx.run(
                    """
                    MERGE (p:Protein {entry: $entry})
                    SET p.entry_name = $entry_name,
                        p.protein_names = $protein_names,
                        p.organism = $organism,
                        p.sequence = $sequence,
                        p.ec_numbers = $ec_numbers,
                        p.interpro_list = $interpro_list
                    """,
                    entry=entry,
                    entry_name=entry_name,
                    protein_names=protein_names,
                    organism=organism,
                    sequence=sequence,
                    ec_numbers=ec_numbers,
                    interpro_list=interpro_list
                )
            
            session.execute_write(create_protein_node)
            print(f"✅ Protéine {entry} ajoutée à Neo4j")
            
            # 2. Créer les relations SIMILAR avec les protéines partageant des domaines InterPro
            if interpro_list:
                def create_similar_relations(tx):
                    result = tx.run(
                        """
                        MATCH (p1:Protein {entry: $entry})
                        MATCH (p2:Protein)
                        WHERE p2.entry <> $entry 
                          AND SIZE(p2.interpro_list) > 0
                          AND any(domain IN p1.interpro_list WHERE domain IN p2.interpro_list)
                        WITH p1, p2, 
                             [domain IN p1.interpro_list WHERE domain IN p2.interpro_list] AS shared_domains
                        WITH p1, p2, shared_domains,
                             toFloat(SIZE(shared_domains)) / 
                             toFloat(SIZE(p1.interpro_list) + SIZE(p2.interpro_list) - SIZE(shared_domains)) AS jaccard_similarity
                        MERGE (p1)-[r:SIMILAR]-(p2)
                        SET r.weight = jaccard_similarity
                        RETURN p2.entry AS target, jaccard_similarity AS weight
                        """,
                        entry=entry
                    )
                    return list(result)
                
                similar_proteins = session.execute_write(create_similar_relations)
                similar_count = len(similar_proteins)
                
                # Construire la liste des relations pour le retour
                for record in similar_proteins:
                    relations.append({
                        "source": entry,
                        "target": record["target"],
                        "weight": record["weight"]
                    })
                
                print(f"✅ {similar_count} relations SIMILAR créées pour {entry}")
            else:
                print(f"⚠️  Aucun domaine InterPro pour {entry}, aucune relation créée")
        
        driver.close()
        return similar_count, relations
        
    except Exception as e:
        print(f"❌ Erreur Neo4j: {e}")
        return -1, []


def add_protein(protein_data):
    """
    Ajoute une protéine à MongoDB et Neo4j avec toutes les relations SIMILAR.
    """
    if not protein_data.get("entry"):
        print("❌ L'ID de la protéine (entry) est requis")
        return {"success": False, "error": "Entry ID is required"}
    
    result = {
        "entry": protein_data.get("entry"),
        "mongodb": {"success": False},
        "neo4j": {"success": False, "similar_count": 0, "relations": []}
    }
    
    # 1. Ajouter à MongoDB
    mongo_id = add_protein_to_mongo(protein_data)
    if mongo_id:
        result["mongodb"]["success"] = True
        result["mongodb"]["id"] = mongo_id
    
    # 2. Ajouter à Neo4j avec les relations SIMILAR
    similar_count, relations = add_protein_to_neo4j(protein_data)
    if similar_count >= 0:
        result["neo4j"]["success"] = True
        result["neo4j"]["similar_count"] = similar_count
        result["neo4j"]["relations"] = relations
    
    result["success"] = result["mongodb"]["success"] and result["neo4j"]["success"]
    
    return result

# Exemple d'utilisation
if __name__ == "__main__":
    # Exemple de protéine à ajouter
    example_protein = {
        "entry": "P11111",
        "entry_name": "TOI_HUMAN",
        "protein_names": "Cytochrome b (Cyt b)",
        "organism": "Homo sapiens (Human)",
        "sequence": "MGDVEKGKKILMEYLENPKKYIPGTKMIFVGIKKKEERADLIAYLKKATNE",
        "ec_numbers": "11.14.1.-",
        "interpro": "IPR001349;IPR002327"
    }
    
    print("=" * 60)
    print("Ajout d'une protéine exemple")
    print("=" * 60)
    
    result = add_protein(example_protein)
    
    print("\n" + "=" * 60)
    print("Résultat:")
    print("=" * 60)
    print(f"Entry: {result['entry']}")
    print(f"MongoDB: {'✅' if result['mongodb']['success'] else '❌'}")
    print(f"Neo4j: {'✅' if result['neo4j']['success'] else '❌'}")
    print(f"Relations SIMILAR créées: {result['neo4j']['similar_count']}")
    
    if result['neo4j']['relations']:
        print("\nRelations créées:")
        for rel in result['neo4j']['relations'][:5]:  # Afficher les 5 premières
            print(f"  - {rel['source']} -> {rel['target']} (weight: {rel['weight']:.4f})")
        if len(result['neo4j']['relations']) > 5:
            print(f"  ... et {len(result['neo4j']['relations']) - 5} autres")
