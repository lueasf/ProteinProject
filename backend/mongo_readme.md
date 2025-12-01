## Configuration de l'environnement

Créez un fichier `.env` à la racine du projet pour sécuriser vos accès :

```ini
MONGO_URI="mongodb://localhost:27017/"
DB_NAME="protein_bank"
COLLECTION_NAME="proteins"
```

-----

## 📥 Importation des Données

Le script `mongo_builder.py` transforme le fichier plat (DataFrame pandas) en documents MongoDB optimisés (nettoyage des chaînes, calcul des longueurs de séquences, création de tableaux).

```bash
python mongo_builder.py
```

**Structure d'un document inséré :**

```json
{
  "_id": "O14756",
  "entry_name": "H17B6_HUMAN",
  "protein_names": ["17-beta-hydroxysteroid dehydrogenase type 6", "17-beta-HSD 6"],
  "organism": "Homo sapiens (Human)",
  "sequence": "MWLY...",
  "sequence_length": 317,
  "annotations": {
    "ec_numbers": ["1.1.1.53", "1.1.1.62"],
    "interpro": ["IPR036291", "IPR020904"]
  }
}
```

-----

## 🔍 Utilisation du Moteur de Recherche (`mongo_queries.py`)

Le coeur du projet réside dans la classe `ProteinDatabase` et sa méthode `advanced_search`. Elle accepte un dictionnaire de filtres pour construire dynamiquement la requête MongoDB.

### Exemple 1 : Recherche Simple

*Rechercher toutes les "Kinases" chez l'Humain.*

```python
from mongo_queries import ProteinDatabase

db = ProteinDatabase()

filters = {
    "keyword": "Kinase",
    "organism": "Human"
}

results = db.advanced_search(filters, page=1)
print(f"Trouvé : {results['total_matches']} protéines.")
```

### Exemple 2 : La Logique "ET" vs "OU" (Puissance du moteur)

C'est ici que le moteur se distingue. Vous pouvez définir la logique pour chaque champ d'annotation.

**Scénario :**
Je cherche une protéine très spécifique qui :

1.  Est **Humaine**.
2.  Possède **À LA FOIS** l'activité EC `1.1.1.53` **ET** `1.1.1.62` (Mode **AND**).
3.  Possède **SOIT** le domaine InterPro `IPR036291` **SOIT** `IPR99999` (Mode **OR**).

<!-- end list -->

```python
complex_filters = {
    "organism": "Human",
    
    # Mode AND : La protéine doit avoir TOUS ces EC numbers
    "ec": {
        "values": ["1.1.1.53", "1.1.1.62"],
        "mode": "AND" 
    },
    
    # Mode OR : La protéine doit avoir AU MOINS UN de ces domaines
    "interpro": {
        "values": ["IPR036291", "IPR99999"],
        "mode": "OR"
    },
    
    # Filtre par taille
    "length": { "min": 300, "max": 400 }
}

results = db.advanced_search(complex_filters)

for protein in results['results']:
    print(f"ID: {protein['_id']} | ECs: {protein['annotations']['ec_numbers']}")
```