from neo4j import GraphDatabase
import csv

# Connexion à Neo4j
uri = "neo4j://127.0.0.1:7687"  # ou l'adresse de ton serveur Neo4j
user = "neo4j"
password = "NoSQLProject"
database_name = "project"
driver = GraphDatabase.driver(uri, auth=(user, password))

def import_nodes(tx, nodes_csv_path):
    with open(nodes_csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            tx.run(
                """
                CREATE (p:Protein {
                    entry: $entry,
                    entry_name: $entry_name,
                    protein_names: $protein_names,
                    organism: $organism,
                    sequence: $sequence,
                    ec_numbers: $ec_numbers,
                    interpro_list: $interpro_list
                })
                """,
                entry=row['Entry'],
                entry_name=row['Entry Name'],
                protein_names=row['Protein names'].split(';') if row['Protein names'] else [],
                organism=row.get('Organism', ''),
                sequence=row['Sequence'],
                ec_numbers=row['EC_numbers'].split(';') if row['EC_numbers'] else [],
                interpro_list=row['InterPro_list'].split(';') if row['InterPro_list'] else []
            )

def import_edges(tx, edges_csv_path):
    with open(edges_csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            tx.run(
                """
                MATCH (p1:Protein {entry: $source}), (p2:Protein {entry: $target})
                CREATE (p1)-[:SIMILAR {weight: $weight}]->(p2)
                """,
                source=row['Source'],
                target=row['Target'],
                weight=float(row['Weight'])
            )

# Exécution
with driver.session(database=database_name) as session:
    session.execute_write(import_nodes, "data/processed/nodes.csv")
    session.execute_write(import_edges, "data/processed/edges.csv")

driver.close()
