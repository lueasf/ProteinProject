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

    def _parse_annotation_groups(self, expression):
        """
        Parse une expression comme "(A AND B) OR (C AND D)" 
        et retourne une liste de groupes: [['A', 'B'], ['C', 'D']]
        Chaque groupe sera combiné avec $all, et les groupes entre eux avec $or
        """
        groups = []
        # Trouver tous les groupes entre parenthèses
        pattern = r'\(([^)]+)\)'
        matches = re.findall(pattern, expression)
        
        for match in matches:
            # Séparer les éléments par AND (insensible à la casse)
            elements = re.split(r'\s+AND\s+', match, flags=re.IGNORECASE)
            group = [elem.strip() for elem in elements if elem.strip()]
            if group:
                groups.append(group)
        
        return groups if groups else None

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

        # 3. Gestion des Annotations (Logique avancée pour EC et InterPro)
        # Supporte: valeurs simples, AND, OR, et combinaisons complexes comme "(A AND B) OR (C AND D)"
        annotation_fields = {
            "ec": "annotations.ec_numbers",
            "interpro": "annotations.interpro"
        }

        for key, mongo_field in annotation_fields.items():
            filter_data = filters.get(key)
            
            if filter_data and filter_data.get("values"):
                values = filter_data["values"]
                
                # Si c'est une chaîne, on parse les groupes
                if isinstance(values, str):
                    # Détection du format avancé: "(A AND B) OR (C AND D)"
                    if "(" in values and ")" in values:
                        # Parser les groupes entre parenthèses
                        groups = self._parse_annotation_groups(values)
                        if groups:
                            or_conditions = []
                            for group in groups:
                                if len(group) == 1:
                                    or_conditions.append({mongo_field: group[0]})
                                else:
                                    or_conditions.append({mongo_field: {"$all": group}})
                            
                            if len(or_conditions) == 1:
                                query.update(or_conditions[0])
                            else:
                                # Combiner avec $or existant si nécessaire
                                if "$and" not in query:
                                    query["$and"] = []
                                query["$and"].append({"$or": or_conditions})
                            continue
                    
                    # Format simple: "1.1.1, 2.2.2"
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

        # 5. Gestion de la recherche par sous-séquence
        if filters.get("sequence"):
            sequence_pattern = filters["sequence"].upper().replace(" ", "")
            query["sequence"] = {"$regex": sequence_pattern, "$options": "i"}

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

    def get_protein_suggestions(self, prefix, limit=10):
        """
        Récupère les suggestions de noms de protéines basées sur un préfixe.
        
        Args:
            prefix (str): Le début du nom de la protéine à rechercher.
            limit (int): Nombre maximum de suggestions à retourner.
        
        Returns:
            list: Liste de dictionnaires avec entry_name et protein_names.
        """
        if not prefix or len(prefix) < 2:
            return []
        
        # Recherche le préfixe n'importe où dans le nom (pas juste au début)
        regex_pattern = re.escape(prefix)
        
        # Recherche dans entry_name et protein_names
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"entry_name": {"$regex": regex_pattern, "$options": "i"}},
                        {"protein_names": {"$regex": regex_pattern, "$options": "i"}}
                    ]
                }
            },
            {
                "$project": {
                    "entry_name": 1,
                    "protein_names": 1,
                    "_id": 0
                }
            },
            {"$limit": limit}
        ]
        
        results = list(self.collection.aggregate(pipeline))
        return results

if __name__ == "__main__":
    db = ProteinDatabase()
    
    # SCÉNARIO : 
    
    my_filters = {
        "keyword": "cytochrome",
    }

    res = db.advanced_search(my_filters)
    
    print(f"Total trouvé : {res['total_matches']}")
    for p in res['results']:
        print(f"ID: {p['_id']}")
        print(f"  -> ECs trouvés: {p['annotations']['ec_numbers']}")
        print(f"  -> IPRs trouvés: {p['annotations']['interpro']}")