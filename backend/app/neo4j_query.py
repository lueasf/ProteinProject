from neo4j import GraphDatabase
import os

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

driver = GraphDatabase.driver(uri, auth=(user, password))


def get_neighbors(entry, limit_k=20, limit_m=10):
    """
    Récupère :
    1. La protéine centrale.
    2. Ses K meilleurs voisins directs.
    3. Ses M meilleurs voisins de second niveau.
    """
    def query(tx):
        # NOUVELLE SYNTAXE NEO4J 5+ : CALL (variables) { ... }
        result = tx.run(
            """
            MATCH (center:Protein {entry: $entry})

            // Étape 1 : Récupérer les K meilleurs voisins directs (n1)
            CALL (center) {
                MATCH (center)-[r1:SIMILAR]-(n1)
                WITH n1, r1
                ORDER BY r1.weight DESC
                LIMIT $limit_k
                RETURN n1
            }

            // Étape 2 : Pour chaque n1, récupérer ses M meilleurs voisins (n2)
            CALL (center, n1) {
                MATCH (n1)-[r2:SIMILAR]-(n2)
                WHERE n2 <> center  // On évite de revenir immédiatement au centre
                WITH n2, r2
                ORDER BY r2.weight DESC
                LIMIT $limit_m
                RETURN collect(n2) AS n2_list
            }

            RETURN center, 
                   collect(n1) AS neighbors1, 
                   collect(n2_list) AS neighbors2_grouped
            """,
            entry=entry, limit_k=limit_k, limit_m=limit_m
        ).single()
        
        if result is None:
            return None

        center = dict(result["center"])
        neighbors1 = [dict(n) for n in result["neighbors1"]]
        
        # Aplatir la liste de listes
        neighbors2 = []
        for group in result["neighbors2_grouped"]:
            for node in group:
                neighbors2.append(dict(node))

        return center, neighbors1, neighbors2

    with driver.session(database=database_name) as session:
        return session.execute_read(query)


def get_edges(entries):
    def query(tx):
        results = tx.run(
            """
            MATCH (a:Protein)-[r:SIMILAR]-(b:Protein)
            WHERE a.entry IN $entries 
              AND b.entry IN $entries
              AND a.entry < b.entry
            RETURN a.entry AS source, 
                   b.entry AS target, 
                   r.weight AS weight
            """,
            entries=entries
        )
        return [{"source": r["source"], "target": r["target"], "weight": r["weight"]} for r in results]

    with driver.session(database=database_name) as session:
        return session.execute_read(query)


def build_subgraph(entry, k=10, m=3):
    result = get_neighbors(entry, limit_k=k, limit_m=m)
    if result is None:
        return None

    center, neighbors1, neighbors2 = result
    
    #print(f"DEBUG: Voisins directs trouvés (k) : {len(neighbors1)}")
    #print(f"DEBUG: Voisins de voisins bruts (m*k) : {len(neighbors2)}")
    
    # --- Déduplication ---
    unique_nodes_map = {}
    
    unique_nodes_map[center['entry']] = center
    
    for node in neighbors1:
        unique_nodes_map[node['entry']] = node
        
    count_new_nodes = 0
    for node in neighbors2:
        # Si le nœud n'est PAS déjà dans la map (donc pas centre, et pas voisin direct)
        if node['entry'] not in unique_nodes_map:
            unique_nodes_map[node['entry']] = node
            count_new_nodes += 1

    #print(f"DEBUG: Voisins de voisins réellement nouveaux ajoutés : {count_new_nodes}")

    nodes = []
    for entry_id, node in unique_nodes_map.items():
        group = "neighbor"
        if entry_id == center["entry"]:
            group = "center"
        
        nodes.append({
            "id": node["entry"],
            "entry": node["entry"],
            "entry_name": node.get("entry_name", ""),
            # "protein_names": node.get("protein_names", ""), # Commenté pour alléger l'affichage console
            "group": group
        })

    edges = get_edges([n["entry"] for n in nodes])

    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    # ESSAIE AVEC k=5, m=5 POUR VOIR
    test_entry = "A0A087X1C5" 
    print(f"--- Lancement pour {test_entry} ---")
    data = build_subgraph(test_entry, k=5, m=5)
    
    if data:
        print("\n--- Résultat Final ---")
        print(f"Total Nœuds uniques : {len(data['nodes'])}")
        print(f"Total Arêtes : {len(data['edges'])}")