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
    driver = None
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        with driver.session(database=NEO4J_DATABASE) as session:
            entry = protein_data.get("entry")
            entry_name = protein_data.get("entry_name", "")
            protein_names = process_protein_names(protein_data.get("protein_names", ""))
            organism = protein_data.get("organism", "")
            sequence = protein_data.get("sequence", "")
            ec_numbers = split_string_to_list(protein_data.get("ec_numbers", ""))
            interpro_list = split_string_to_list(protein_data.get("interpro", ""))
            
            # 1. Créer ou mettre à jour le nœud Protein
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
            print(f"✅ Nœud Protein {entry} créé/mis à jour dans Neo4j")
            
            # 2. Si pas de domaines InterPro, pas de relations SIMILAR
            if not interpro_list:
                print(f"ℹ️ Pas de domaines InterPro pour {entry}, aucune relation SIMILAR créée")
                return (0, [])
            
            # 3. Trouver les protéines avec des domaines InterPro en commun
            def find_similar_proteins(tx):
                result = tx.run(
                    """
                    MATCH (other:Protein)
                    WHERE other.entry <> $entry
                      AND other.interpro_list IS NOT NULL
                      AND (
                          // Cas 1: interpro_list est une vraie liste Neo4j
                          (other.interpro_list[0] IS NOT NULL 
                           AND size([d IN other.interpro_list WHERE d IN $interpro_list]) > 0)
                          OR
                          // Cas 2: interpro_list est une string (anciennes données)
                          (other.interpro_list[0] IS NULL 
                           AND ANY(domain IN $interpro_list WHERE other.interpro_list CONTAINS domain))
                      )
                    RETURN other.entry AS other_entry,
                           other.interpro_list AS other_interpro
                    """,
                    entry=entry,
                    interpro_list=interpro_list
                )
                return [(record["other_entry"], record["other_interpro"]) for record in result]
            
            similar_proteins = session.execute_read(find_similar_proteins)
            
            if not similar_proteins:
                print(f"ℹ️ Aucune protéine similaire trouvée pour {entry}")
                return (0, [])
            
            # 4. Calculer les poids et créer les relations SIMILAR
            relations_created = []
            
            def create_similar_relation(tx, other_entry, weight):
                # Supprimer d'abord les relations existantes entre ces deux protéines
                tx.run(
                    """
                    MATCH (p1:Protein {entry: $entry})-[r:SIMILAR]-(p2:Protein {entry: $other_entry})
                    DELETE r
                    """,
                    entry=entry,
                    other_entry=other_entry
                )
                # Créer la nouvelle relation bidirectionnelle (une seule arête)
                tx.run(
                    """
                    MATCH (p1:Protein {entry: $entry})
                    MATCH (p2:Protein {entry: $other_entry})
                    CREATE (p1)-[:SIMILAR {weight: $weight}]->(p2)
                    """,
                    entry=entry,
                    other_entry=other_entry,
                    weight=weight
                )
            
            for other_entry, other_interpro in similar_proteins:
                # Gérer le cas où other_interpro est une string (anciennes données)
                if isinstance(other_interpro, str):
                    # Parser la string "['IPR001', 'IPR002']" en liste
                    try:
                        other_interpro_list = ast.literal_eval(other_interpro)
                    except:
                        # Fallback: extraire les IPR avec regex
                        other_interpro_list = re.findall(r'IPR\d+', other_interpro)
                else:
                    other_interpro_list = other_interpro if other_interpro else []
                
                # Calcul du poids Jaccard: intersection / union
                set_new = set(interpro_list)
                set_other = set(other_interpro_list)
                
                intersection = len(set_new & set_other)
                union = len(set_new | set_other)
                weight = intersection / union if union > 0 else 0
                
                session.execute_write(create_similar_relation, other_entry, weight)
                relations_created.append({
                    "source": entry,
                    "target": other_entry,
                    "weight": weight,
                    "shared_domains": list(set_new & set_other)
                })
            
            print(f"✅ {len(relations_created)} relations SIMILAR créées pour {entry}")
            return (len(relations_created), relations_created)
            
    except Exception as e:
        print(f"❌ Erreur Neo4j: {e}")
        return (0, [])
    finally:
        if driver:
            driver.close()


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
