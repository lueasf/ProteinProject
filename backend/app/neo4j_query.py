from neo4j import GraphDatabase
import os

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

driver = GraphDatabase.driver(uri, auth=(user, password))

def get_neighbors(entry):
    """
    Récupère une protéine, ses voisins directs et voisins de voisins.
    """
    def query(tx):
        # On utilise des sets/distinct dans Cypher, mais le tri final se fera en Python
        result = tx.run(
            """
            MATCH (p:Protein {entry: $entry})
            
            // Récupère les voisins directs
            OPTIONAL MATCH (p)-[:SIMILAR]-(n1)
            
            // Récupère les voisins de niveau 2
            OPTIONAL MATCH (n1)-[:SIMILAR]-(n2)
            
            RETURN p AS center, 
                   collect(DISTINCT n1) AS neighbors1, 
                   collect(DISTINCT n2) AS neighbors2
            """,
            entry=entry
        ).single()
        
        if result is None:
            return None

        center = dict(result["center"])
        # On filtre les None au cas où il n'y a pas de voisins
        neighbors1 = [dict(n) for n in result["neighbors1"] if n]
        neighbors2 = [dict(n) for n in result["neighbors2"] if n]

        return center, neighbors1, neighbors2

    with driver.session(database=database_name) as session:
        return session.execute_read(query)

def get_edges(entries):
    """
    Récupère toutes les arêtes SIMILAR entre les protéines listées.
    Évite les doublons A-B / B-A.
    """
    def query(tx):
        results = tx.run(
            """
            MATCH (a:Protein)-[r:SIMILAR]-(b:Protein)
            WHERE a.entry IN $entries 
              AND b.entry IN $entries
              AND a.entry < b.entry  // ASTUCE : Force une direction unique pour éviter les doublons
            RETURN a.entry AS source, 
                   b.entry AS target, 
                   r.weight AS weight
            """,
            entries=entries
        )
        
        return [
            {
                "source": record["source"],
                "target": record["target"],
                "weight": record["weight"]
            }
            for record in results
        ]

    with driver.session(database=database_name) as session:
        return session.execute_read(query)

def build_subgraph(entry):
    result = get_neighbors(entry)
    if result is None:
        return None

    center, neighbors1, neighbors2 = result
    
    # --- CORRECTION 1 : Déduplication des nœuds ---
    # On utilise un dictionnaire indexé par 'entry' pour écraser les doublons
    unique_nodes_map = {}
    
    # 1. Ajouter le centre
    unique_nodes_map[center['entry']] = center
    
    # 2. Ajouter neighbors1
    for node in neighbors1:
        unique_nodes_map[node['entry']] = node
        
    # 3. Ajouter neighbors2 (si un nœud existe déjà, il ne sera pas dupliqué, ou juste écrasé par le même contenu)
    for node in neighbors2:
        # On s'assure de ne pas ajouter le centre s'il est revenu dans la boucle
        if node['entry'] != center['entry']:
            unique_nodes_map[node['entry']] = node

    # Transformation en liste propre pour le JSON
    nodes = []
    for entry_id, node in unique_nodes_map.items():
        nodes.append({
            "id": node["entry"],
            "entry": node["entry"],
            "entry_name": node.get("entry_name", ""),
            "protein_names": node.get("protein_names", ""),
            "organism": node.get("organism", ""),
            "ec_numbers": node.get("ec_numbers", []),
            "interpro_list": node.get("interpro_list", []),
            # Tu peux ajouter un champ pour le frontend pour distinguer les types
            "group": "center" if entry_id == center["entry"] else "neighbor"
        })

    # --- Récupération des arêtes sur la liste dédoublonnée ---
    entries_list = [n["entry"] for n in nodes]
    edges = get_edges(entries_list)

    return {
        "nodes": nodes,
        "edges": edges
    }

if __name__ == "__main__":
    # Test
    data = build_subgraph("A0A087X1C5")
    if data:
        print(f"Nombre de nœuds : {len(data['nodes'])}")
        print(f"Nombre d'arêtes : {len(data['edges'])}")
        # print(data)
    else:
        print("Protéine introuvable.")