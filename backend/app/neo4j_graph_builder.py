from neo4j import GraphDatabase
import csv
from tqdm import tqdm
import os
import ast  # Pour parser les listes dans le CSV

# Connexion à Neo4j
uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")
driver = GraphDatabase.driver(uri, auth=(user, password))

def clear_database(session):
    """Supprime tous les nœuds et relations de la base de données par lots"""
    print("🗑️ Nettoyage de la base de données...")
    
    # Compter le nombre total de nœuds
    def count_nodes(tx):
        result = tx.run("MATCH (n) RETURN count(n) as total")
        return result.single()["total"]
    
    total_nodes = session.execute_read(count_nodes)
    
    if total_nodes == 0:
        print("✅ Base de données déjà vide")
        return
    
    # Supprimer par lots pour éviter les problèmes de mémoire
    batch_size = 1000
    deleted = 1
    
    with tqdm(total=total_nodes, desc="Suppression des nœuds") as pbar:
        while deleted > 0:
            def delete_batch(tx):
                result = tx.run(
                    """
                    MATCH (n)
                    WITH n LIMIT $limit
                    DETACH DELETE n
                    RETURN count(n) as deleted
                    """,
                    limit=batch_size
                )
                return result.single()["deleted"]
            
            deleted = session.execute_write(delete_batch)
            pbar.update(deleted)
    
    print("✅ Base de données Neo4j nettoyée")

def import_nodes_optimized(session, nodes_csv_path, batch_size=500):
    """Import des nœuds avec transactions séparées pour éviter OOM"""
    with open(nodes_csv_path, newline='', encoding='utf-8') as csvfile:
        total_rows = sum(1 for _ in csvfile) - 1
        csvfile.seek(0)
        reader = csv.DictReader(csvfile)
        batch = []
        
        for row in tqdm(reader, total=total_rows, desc="Import des nœuds"):
            # Parser les listes depuis le CSV
            try:
                interpro_list = ast.literal_eval(row['InterPro_list']) if row['InterPro_list'] else []
            except:
                interpro_list = row['InterPro_list'].split(';') if row['InterPro_list'] else []
            
            try:
                ec_numbers = ast.literal_eval(row['EC_numbers']) if row['EC_numbers'] else []
            except:
                ec_numbers = row['EC_numbers'].split(';') if row['EC_numbers'] else []
            
            batch.append({
                'entry': row['Entry'],
                'entry_name': row['Entry Name'],
                'protein_names': row['Protein names'].split(';') if row['Protein names'] else [],
                'organism': row.get('Organism', ''),
                'sequence': row['Sequence'],
                'ec_numbers': ec_numbers,
                'interpro_list': interpro_list
            })
            
            if len(batch) >= batch_size:
                session.execute_write(lambda tx, b=batch: tx.run(
                    """
                    UNWIND $batch AS node
                    CREATE (p:Protein {
                        entry: node.entry,
                        entry_name: node.entry_name,
                        protein_names: node.protein_names,
                        organism: node.organism,
                        sequence: node.sequence,
                        ec_numbers: node.ec_numbers,
                        interpro_list: node.interpro_list
                    })
                    """,
                    batch=b
                ))
                batch = []
        
        if batch:
            session.execute_write(lambda tx, b=batch: tx.run(
                """
                UNWIND $batch AS node
                CREATE (p:Protein {
                    entry: node.entry,
                    entry_name: node.entry_name,
                    protein_names: node.protein_names,
                    organism: node.organism,
                    sequence: node.sequence,
                    ec_numbers: node.ec_numbers,
                    interpro_list: node.interpro_list
                })
                """,
                batch=b
            ))

def create_indexes(tx):
    """Créer des index pour optimiser les MATCH"""
    tx.run("CREATE INDEX protein_entry IF NOT EXISTS FOR (p:Protein) ON (p.entry)")
    print("✅ Index créé sur Protein.entry")

def import_edges_optimized(session, edges_csv_path, batch_size=8000):
    """Import des arêtes avec transactions séparées"""
    with open(edges_csv_path, newline='', encoding='utf-8') as csvfile:
        total_rows = sum(1 for _ in csvfile) - 1
        csvfile.seek(0)
        reader = csv.DictReader(csvfile)
        batch = []
        
        for row in tqdm(reader, total=total_rows, desc="Import des arêtes"):
            batch.append({
                'source': row['Source'],
                'target': row['Target'],
                'weight': float(row['Weight'])
            })
            
            if len(batch) >= batch_size:
                session.execute_write(lambda tx, b=batch: tx.run(
                    """
                    UNWIND $batch AS edge
                    MATCH (p1:Protein {entry: edge.source})
                    MATCH (p2:Protein {entry: edge.target})
                    CREATE (p1)-[:SIMILAR {weight: edge.weight}]->(p2)
                    """,
                    batch=b
                ))
                batch = []
        
        if batch:
            session.execute_write(lambda tx, b=batch: tx.run(
                """
                UNWIND $batch AS edge
                MATCH (p1:Protein {entry: edge.source})
                MATCH (p2:Protein {entry: edge.target})
                CREATE (p1)-[:SIMILAR {weight: edge.weight}]->(p2)
                """,
                batch=b
            ))

# Exécution
if __name__ == "__main__":
    with driver.session(database=database_name) as session:
        # 1. Nettoyage de la base
        clear_database(session)
        
        # 2. Créer les index
        session.execute_write(create_indexes)
        
        # 3. Import des nœuds
        import_nodes_optimized(session, "backend/data/processed/nodes.csv")
        
        # 4. Import des arêtes
        import_edges_optimized(session, "backend/data/processed/edges.csv")

driver.close()
