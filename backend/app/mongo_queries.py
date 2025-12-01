import os
import dotenv
from pymongo import MongoClient
import re

dotenv.load_dotenv()

class ProteinDatabase:
    def __init__(self):
        self.mongo_uri = os.getenv("MONGO_URI")
        self.db_name = os.getenv("DB_NAME")
        self.collection_name = os.getenv("COLLECTION_NAME")
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client[self.db_name]
            self.collection = self.db[self.collection_name]
        except Exception as e:
            print(f"❌ Erreur connexion : {e}")

    def advanced_search(self, filters, page=1, page_size=20):
        """
        Recherche avancée basée sur un dictionnaire de filtres.
        
        Args:
            filters (dict): Dictionnaire contenant les critères (voir exemple).
            page (int): Pagination.
            page_size (int): Taille de page.
        """
        query = {}

        # 1. Gestion du Keyword (Recherche textuelle globale)
        if filters.get("keyword"):
            regex = re.compile(filters["keyword"], re.IGNORECASE)
            query["$or"] = [
                {"entry_name": {"$regex": regex}},
                {"protein_names": {"$regex": regex}}
            ]

        # 2. Gestion de l'Organisme
        if filters.get("organism"):
            query["organism"] = {"$regex": re.compile(filters["organism"], re.IGNORECASE)}

        # 3. Gestion des Annotations (Logique générique pour EC et InterPro)
        # On crée une petite map pour lier ton filtre au champ réel dans MongoDB
        annotation_fields = {
            "ec": "annotations.ec_numbers",
            "interpro": "annotations.interpro"
        }

        for key, mongo_field in annotation_fields.items():
            filter_data = filters.get(key) # Récupère le sous-dictionnaire (values + mode)
            
            if filter_data and filter_data.get("values"):
                values = filter_data["values"]
                
                # Si c'est une chaine "1.1.1, 2.2.2", on la transforme en liste
                if isinstance(values, str):
                    values = [x.strip() for x in values.split(',') if x.strip()]
                
                # Définition du mode (OR par défaut)
                mode = filter_data.get("mode", "OR").upper()
                operator = "$all" if mode == "AND" else "$in"
                
                # Construction de la requête
                if len(values) == 1:
                    query[mongo_field] = values[0]
                else:
                    query[mongo_field] = {operator: values}

        # 4. Gestion de la longueur (Range)
        length_data = filters.get("length")
        if length_data:
            range_query = {}
            if length_data.get("min"):
                range_query["$gte"] = int(length_data["min"])
            if length_data.get("max"):
                range_query["$lte"] = int(length_data["max"])
            
            if range_query:
                query["sequence_length"] = range_query

        # --- Exécution ---
        skip_amount = (page - 1) * page_size
        
        if not query:
            total_results = self.collection.estimated_document_count()
        else:
            total_results = self.collection.count_documents(query)

        cursor = self.collection.find(query, {"sequence": 0}).skip(skip_amount).limit(page_size)

        return {
            "total_matches": total_results,
            "page": page,
            "per_page": page_size,
            "results": list(cursor)
        }

if __name__ == "__main__":
    db = ProteinDatabase()

    print("\n--- TEST HYBRIDE (AND pour EC, OR pour InterPro) ---")
    
    # SCÉNARIO : 
    # Je veux une protéine qui possède A LA FOIS les EC 1.1.1.53 ET 1.1.1.62 (AND)
    # MAIS qui peut avoir SOIT le domaine IPR036291 SOIT IPR99999 (OR)
    
    my_filters = {
        "organism": "Human",
        "ec": {
            "values": ["1.1.1.53", "1.1.1.62"], # Ta protéine O14756 a les deux
            "mode": "AND"
        },
        "interpro": {
            "values": ["IPR036291", "IPR99999"], # Ta protéine a le premier, pas le second
            "mode": "OR"
        },
        "length": { "min": 300, "max": 400 }
    }

    res = db.advanced_search(my_filters)
    
    print(f"Total trouvé : {res['total_matches']}")
    for p in res['results']:
        print(f"ID: {p['_id']}")
        print(f"  -> ECs trouvés: {p['annotations']['ec_numbers']}")
        print(f"  -> IPRs trouvés: {p['annotations']['interpro']}")