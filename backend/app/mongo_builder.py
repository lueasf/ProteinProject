from pymongo import MongoClient
import os
import dotenv
import pandas as pd
import re

dotenv.load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")


# Fonction pour nettoyer et diviser les chaînes (InterPro, EC)
def split_string_to_list(val, delimiter=';'):
    if pd.isna(val) or val == '':
        return []
    # Divise, enlève les espaces autour et filtre les chaînes vides
    return [x.strip() for x in str(val).split(delimiter) if x.strip()]

# Fonction pour nettoyer les noms de protéines 
def process_protein_names(val):
    if pd.isna(val):
        return []
    names = re.split(r'\s*\(', val)
    clean_names = []
    for n in names:
        n = n.replace(')', '').strip()
        # On évite d'inclure les EC number qui traînent dans les noms
        if not n.startswith('EC '): 
            clean_names.append(n)
    return clean_names


def prepare_mongo_documents(tsv_path):
    df = pd.read_csv(tsv_path, sep='\t')
    mongo_docs = []

    for index, row in df.iterrows():
        doc = {
            # _id est indexé par défaut et garantit l'unicité
            "_id": row['Entry'],
            
            "entry_name": row['Entry Name'],
            
            # Transformation du nom en liste
            "protein_names": process_protein_names(row['Protein names']),
            
            "organism": row['Organism'],
            
            "sequence": row['Sequence'],
            
            # Pré-calculer la longueur accélère les filtres futurs (ex: sequence > 50 AA)
            "sequence_length": len(row['Sequence']) if not pd.isna(row['Sequence']) else 0,
            
            "annotations": {
                # Transformation des chaînes "1.1.1; 2.2.2" en listes réelles
                "ec_numbers": split_string_to_list(row['EC number']),
                "interpro": split_string_to_list(row['InterPro'])
            }
        }
        mongo_docs.append(doc)

    return mongo_docs

if __name__ == "__main__":
    tsv_path = os.path.join('backend', 'data', 'raw', 'uniprot.tsv')
    
    df = pd.read_csv(tsv_path, sep='\t')

    # Préparation des documents MongoDB
    mongo_docs = prepare_mongo_documents('backend/data/raw/uniprot.tsv')

    # Connexion à MongoDB et insertion des documents
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    collection.insert_many(mongo_docs)