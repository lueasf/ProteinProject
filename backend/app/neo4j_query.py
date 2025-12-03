from neo4j import GraphDatabase
import os

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

driver = GraphDatabase.driver(uri, auth=(user, password))


def get_neighbors(entry, limit_k=20, limit_m=10):
    
    # 1. La requête complète modifiée pour inclure les poids
    def query_full(tx):
        result = tx.run(
            """
            MATCH (center:Protein {entry: $entry})

            // Étape 1 : Voisins directs (n1) ET leur poids (r1.weight)
            CALL (center) {
                MATCH (center)-[r1:SIMILAR]-(n1)
                WITH n1, r1
                ORDER BY r1.weight DESC
                LIMIT $limit_k
                // On renvoie une map contenant les données du nœud et le score
                RETURN {data: properties(n1), score: r1.weight} AS n1_obj
            }

            // Étape 2 : Voisins de voisins (n2) ET leur poids (r2.weight)
            CALL (center, n1_obj) {
                // On doit retrouver le nœud n1 à partir de ses propriétés ou ID pour continuer
                // (Note: passer des nodes entiers dans les maps est parfois lourd, ici on fait simple)
                WITH n1_obj
                MATCH (n1:Protein {entry: n1_obj.data.entry})
                
                MATCH (n1)-[r2:SIMILAR]-(n2)
                WHERE n2.entry <> center.entry
                WITH n2, r2
                ORDER BY r2.weight DESC
                LIMIT $limit_m
                RETURN collect({data: properties(n2), score: r2.weight}) AS n2_list
            }

            RETURN center, 
                   collect(n1_obj) AS neighbors1, 
                   collect(n2_list) AS neighbors2_grouped
            """,
            entry=entry, limit_k=limit_k, limit_m=limit_m
        ).single()
        
        if result is None:
            return None

        center = dict(result["center"])
        
        # Extraction : neighbors1 est maintenant une liste d'objets {data: {}, score: float}
        neighbors1 = [
            {"node": res["data"], "score": res["score"]} 
            for res in result["neighbors1"]
        ]
        
        # Extraction : neighbors2 est une liste de listes d'objets
        neighbors2 = []
        for group in result["neighbors2_grouped"]:
            for item in group:
                neighbors2.append({"node": item["data"], "score": item["score"]})

        return center, neighbors1, neighbors2

    # 2. La requête de secours (si le nœud est isolé)
    def query_center_only(tx):
        result = tx.run(
            """
            MATCH (p:Protein {entry: $entry})
            RETURN p AS center
            """, 
            entry=entry
        ).single()
        
        if result is None:
            return None
            
        # On renvoie le centre avec des listes de voisins vides
        return dict(result["center"]), [], []

    with driver.session(database=database_name) as session:
        # On tente d'abord la requête complète
        data = session.execute_read(query_full)
        
        # Si la requête complète renvoie des données, c'est parfait
        if data is not None:
            return data
            
        # Sinon, cela peut vouloir dire 2 choses :
        # A. La protéine n'existe pas
        # B. La protéine existe mais n'a pas de voisins (le CALL a échoué)
        # On vérifie donc si elle existe seule :
        return session.execute_read(query_center_only)


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
    
    unique_nodes_map = {}
    
    # 1. Centre (Score = 1.0 ou None)
    unique_nodes_map[center['entry']] = {
        "data": center,
        "group": "center",
        "score": 1.0
    }
    
    # 2. Voisins directs
    for item in neighbors1:
        node_data = item["node"]
        score = item["score"]
        if node_data['entry'] not in unique_nodes_map:
            unique_nodes_map[node_data['entry']] = {
                "data": node_data,
                "group": "level1",
                "score": score  # On stocke le score ici
            }
        
    # 3. Voisins de voisins
    for item in neighbors2:
        node_data = item["node"]
        score = item["score"]
        if node_data['entry'] not in unique_nodes_map:
            unique_nodes_map[node_data['entry']] = {
                "data": node_data,
                "group": "level2",
                "score": score
            }

    # Construction de la liste
    nodes = []
    for entry_id, info in unique_nodes_map.items():
        node_data = info["data"]
        
        nodes.append({
            "id": node_data.get("entry", ""),
            "entry": node_data.get("entry", ""),
            "entry_name": node_data.get("entry_name", ""),
            "protein_names": node_data.get("protein_names", []),
            "organism": node_data.get("organism", ""),
            "sequence": node_data.get("sequence", ""),
            "ec_numbers": node_data.get("ec_numbers", []),
            "interpro_list": node_data.get("interpro_list", []),
            "group": info["group"],
            "similarity": info["score"]  # Ajouté au JSON final
        })

    edges = get_edges([n["entry"] for n in nodes])
    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    test_entry = "A0A087X1C5" 
    print(f"--- Lancement pour {test_entry} ---")
    data = build_subgraph(test_entry, k=5, m=5)
    
    if data:
        print("\n--- Résultat Final ---")
        print(f"Total Nœuds uniques : {len(data['nodes'])}")
        print(f"Total Arêtes : {len(data['edges'])}")