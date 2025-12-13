import os
from typing import Dict
from neo4j import GraphDatabase
import dotenv

dotenv.load_dotenv()

# Configuration Neo4j
uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")


def _get_driver():
    """Crée et retourne un driver Neo4j."""
    return GraphDatabase.driver(uri, auth=(user, password))


def compute_protein_stats() -> Dict[str, float]:
    """
    Calcule des statistiques globales à partir de la base Neo4j.

    Renvoie un dict avec :
      - total_proteins
      - labelled_proteins    (au moins une annotation EC_numbers non vide)
      - unlabelled_proteins
      - isolated_proteins    (aucun voisin dans les relations SIMILAR)
      - labelled_ratio       (labelled / total)
      - isolated_ratio       (isolated / total)
    """
    driver = _get_driver()
    
    try:
        with driver.session(database=database_name) as session:
            
            # Requête pour obtenir toutes les statistiques en une seule fois
            def get_stats(tx):
                result = tx.run(
                    """
                    // Total des protéines
                    MATCH (p:Protein)
                    WITH count(p) AS total_proteins
                    
                    // Protéines labellées (ec_numbers non vide)
                    OPTIONAL MATCH (labelled:Protein)
                    WHERE labelled.ec_numbers IS NOT NULL 
                      AND size(labelled.ec_numbers) > 0
                    WITH total_proteins, count(labelled) AS labelled_proteins
                    
                    // Protéines isolées (sans relation SIMILAR)
                    OPTIONAL MATCH (isolated:Protein)
                    WHERE NOT (isolated)-[:SIMILAR]-()
                    WITH total_proteins, labelled_proteins, count(isolated) AS isolated_proteins
                    
                    RETURN total_proteins, labelled_proteins, isolated_proteins
                    """
                )
                return result.single()
            
            stats_result = session.execute_read(get_stats)
            
            if stats_result is None:
                # Base vide
                return {
                    "total_proteins": 0,
                    "labelled_proteins": 0,
                    "unlabelled_proteins": 0,
                    "isolated_proteins": 0,
                    "labelled_ratio": 0.0,
                    "isolated_ratio": 0.0,
                }
            
            total_proteins = stats_result["total_proteins"]
            labelled_proteins = stats_result["labelled_proteins"]
            isolated_proteins = stats_result["isolated_proteins"]
            
            unlabelled_proteins = total_proteins - labelled_proteins
            
            labelled_ratio = (labelled_proteins / total_proteins * 100.0) if total_proteins else 0.0
            isolated_ratio = (isolated_proteins / total_proteins * 100.0) if total_proteins else 0.0
            
            return {
                "total_proteins": total_proteins,
                "labelled_proteins": labelled_proteins,
                "unlabelled_proteins": unlabelled_proteins,
                "isolated_proteins": isolated_proteins,
                "labelled_ratio": labelled_ratio,
                "isolated_ratio": isolated_ratio,
            }
    
    finally:
        driver.close()


if __name__ == "__main__":
    stats = compute_protein_stats()
    print("=== Protein statistics (from Neo4j) ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
