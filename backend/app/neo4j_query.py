from neo4j import GraphDatabase
import os

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

driver = GraphDatabase.driver(uri, auth=(user, password))


def get_neighbors(entry):
    """
    Récupère une protéine, ses voisins directs (1-hop)
    et les voisins des voisins (2-hops).
    """
    with driver.session(database=database_name) as session:
        result = session.execute_read(
            lambda tx: tx.run(
                """
                MATCH (p:Protein {entry: $entry})

                OPTIONAL MATCH (p)-[:SIMILAR]-(n1)
                OPTIONAL MATCH (n1)-[:SIMILAR]-(n2)

                RETURN p AS center,
                       collect(DISTINCT n1) AS neighbors1,
                       collect(DISTINCT n2) AS neighbors2
                """,
                entry=entry
            ).single()
        )

        if result is None:
            return None

        center = result["center"]
        neighbors1 = [n for n in result["neighbors1"] if n]
        neighbors2 = [n for n in result["neighbors2"] if n]

        # Supprime le nœud central des voisins de voisins s'il apparaît
        neighbors2 = [n for n in neighbors2 if n["entry"] != entry]

        return center, neighbors1, neighbors2


def get_edges(entries):
    """
    Récupère toutes les arêtes SIMILAR entre les protéines listées.
    """
    with driver.session(database=database_name) as session:
        results = session.execute_read(
            lambda tx: tx.run(
                """
                MATCH (a:Protein)-[r:SIMILAR]-(b:Protein)
                WHERE a.entry IN $entries AND b.entry IN $entries
                RETURN a.entry AS source,
                       b.entry AS target,
                       r.weight AS weight
                """,
                entries=entries
            )
        )

        return [
            {
                "source": record["source"],
                "target": record["target"],
                "weight": record["weight"]
            }
            for record in results
        ]


def build_subgraph(entry):
    """
    Construit un mini-graphe autour d'une protéine :
    - nœud central
    - voisins directs
    - voisins des voisins
    - arêtes correspondantes
    """
    result = get_neighbors(entry)
    if result is None:
        return None

    center, neighbors1, neighbors2 = result

    # Liste de tous les nœuds uniques
    all_nodes = [center] + neighbors1 + neighbors2

    # Convertit les noeuds Neo4j en dict
    nodes = []
    for node in all_nodes:
        nodes.append({
            "id": node["entry"],
            "entry": node["entry"],
            "entry_name": node["entry_name"],
            "protein_names": node["protein_names"],
            "organism": node.get("organism", ""),
            "ec_numbers": node.get("ec_numbers", []),
            "interpro_list": node.get("interpro_list", []),
        })

    edges = get_edges([n["entry"] for n in nodes])

    return {
        "nodes": nodes,
        "edges": edges
    }


if __name__ == "__main__":
    test = build_subgraph("A0A087X1C5")  # exemple
    print(test)
