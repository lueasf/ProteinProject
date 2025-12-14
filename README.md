# Projet


# Protein Database Explorer - Documentation

## Aperçu du projet

**Protein Database Explorer** est une application web complète permettant de stocker, rechercher, analyser et visualiser des données protéiques à l'aide de bases de données NoSQL (MongoDB et Neo4j). L'application comprend également un système de propagation de labels pour prédire automatiquement les fonctions enzymatiques (numéros EC) des protéines non annotées.

### Fonctionnalités principales
- 🔍 **Recherche avancée** dans MongoDB avec auto-complétion en temps réel
- 📊 **Visualisation interactive** des réseaux de similarité dans Neo4j
- 🏷️ **Propagation automatique** des annotations EC
- 📈 **Tableau de bord statistique** avec historiques
- ➕ **CRUD complet** (Ajout/Suppression synchronisée MongoDB/Neo4j)
- 🧪 **Évaluation du modèle** avec validation répétée


## Installation et démarrage

### Prérequis
- Python 3.9+
- MongoDB (version 5.0+)
- Neo4j (version 5.0+)
- Streamlit

### 1. Configuration de l'environnement

#### Installer les dépendances Python
```bash
pip install -r requirements.txt
```

**requirements.txt** :
```
pandas
neo4j
pymongo
python-dotenv
tqdm
streamlit
streamlit-searchbox
plotly
numpy
scikit-learn
```

### 2. Configuration des bases de données

#### a) MongoDB
1. Installer MongoDB
2. Démarrer le service MongoDB

#### b) Neo4j
1. Télécharger Neo4j Desktop
2. Créer une nouvelle base de données
3. Noter les identifiants de connexion

### c) Créer un fichier `.env` à la racine du projet axé sur le .env.example

```env
# MongoDB
MONGO_URI=mongodb://localhost:27017
DB_NAME=protein_database
COLLECTION_NAME=proteins

# Neo4j
NEO4J_URI=neo4j://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=votre_mot_de_passe
NEO4J_DATABASE_NAME=project
```

### 3. Préparation des données 

#### b) Chargement des données initiales
1. Placer votre fichier `uniprot.tsv` dans `backend/data/raw/`
2. Exécuter les scripts de remplissage des bases de données :

```bash
python backend/app/graph_builder.py
python backend/app/neo4j_graph_builder.py
python backend/app/mongo_builder.py
```

```bash
streamlit run frontend/app/pages/front.py
```
L'application sera accessible à l'adresse : http://localhost:8501

## Interface principale

### 1. Recherche de protéines
- **Barre de recherche centrale** : Auto-complétion en temps réel  
- **Filtres avancés** dans la sidebar :
  - Recherche par mot-clé  
  - Filtres EC (logique AND/OR avancée)  
  - Filtres InterPro  
  - Longueur de séquence  
  - Organisme  

### 2. Visualisation des graphes
- Cliquez sur **"Afficher le graphe"** dans un résultat  
- **Paramètres ajustables** :
  - `k` : Nombre de voisins directs  
  - `m` : Nombre de voisins de voisins  
- **Légende des couleurs** :
  - 🔴 Rouge : Protéine centrale  
  - 🔵 Bleu : Voisins directs  
  - 🟢 Vert : Voisins de niveau 2  

### 3. Gestion des données
- **Ajouter une protéine** : Bouton "Ajouter une protéine"  
- **Supprimer une protéine** : Bouton dans les détails de la protéine  
- **Synchronisation automatique** entre MongoDB et Neo4j  

### 4. Statistiques
- Accédez aux statistiques globales en bas de page  
- Calculez des *snapshots* à différents moments  
- Visualisez l’évolution avec les graphiques  

### 5. Propagation de labels
- **Validation** : Évalue les performances du modèle  
- **Prédiction** : Attribue des EC aux protéines non annotées  
- **Métriques** : Précision, Rappel, F1-score par niveau EC  


## Backend python
backend/app/
├── mongo_queries.py        # Recherche avancée MongoDB
├── neo4j_query.py          # Requêtes et graphes Neo4j
├── label_propagation.py    # Algorithme de propagation
├── label_propagation2.py   # Propagation hiérarchique
├── graph_builder.py        # Construction du graphe
├── neo4j_graph_builder.py  # Import dans Neo4j
├── mongo_builder.py        # Import dans MongoDB
├── add_protein.py          # CRUD - Ajout
├── delete_protein.py       # CRUD - Suppression
├── stats.py                # Statistiques
└── mongo_reset.py          # Réinitialisation

## Problèmes courants

### Vérifier que MongoDB est en route
```
sudo systemctl status mongod
```

### Tester la connexion
```
python -c "from pymongo import MongoClient; client = MongoClient('mongodb://localhost:27017'); print(client.server_info())"
```


## 📊 Structure des données

### Format d'entrée (uniprot.tsv)

| Colonne        | Description                                   |
|----------------|-----------------------------------------------|
| Entry          | Identifiant unique (clé primaire)             |
| Entry Name     | Nom court                                     |
| Protein names  | Noms complets                                 |
| Organism       | Espèce source                                 |
| Sequence       | Séquence d'acides aminés                      |
| EC number      | Numéro(s) EC (séparés par `;`)                |
| InterPro       | Domaines InterPro (séparés par `;`)           |

---

### Modèle MongoDB

```json
{
  "_id": "P12345",
  "entry_name": "SRD_HUMAN",
  "protein_names": ["Cytochrome b", "Cyt b"],
  "organism": "Homo sapiens (Human)",
  "sequence": "MGDVEKGKKI...",
  "sequence_length": 156,
  "annotations": {
    "ec_numbers": ["1.14.14.1", "4.2.1.152"],
    "interpro": ["IPR001349", "IPR002327"]
  }
}
```

## Setup MongoDB
### Sur Linux

```bash
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | sudo gpg –dearmor -o /usr/share/keyrings/mongodb.gpg echo “deb [ arch=amd64 signed-by=/usr/share/keyrings/mongodb.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse” | sudo tee /etc/apt/ sources.list.d/mongodb-org-7.0.list sudo apt-get update sudo apt-get install -y mongodb-org
```

Dans un terminal
```bash
mkdir mongobin
cd mongobin
mongod --dbpath .
```

Dans un autre terminal
```bash
mongosh
```

Attention : supprimez le dossier mongobin si vous voulez réinitialiser la base de données. 


## Construction du graphe de similarité
- **Extraction CSV** : [backend/app/graph_builder.py](backend/app/graph_builder.py) lit le fichier TSV brut, nettoie les colonnes (InterPro, EC) et exporte deux jeux de données :
  - `backend/data/processed/nodes.csv` : chaque protéine, sa liste d’InterPro, ses numéros EC normalisés et les labels hiérarchiques générés.
  - `backend/data/processed/edges.csv` : toutes les paires de protéines partageant au moins un domaine InterPro, pondérées par le score Jaccard.
- **Import Neo4j** : [backend/app/neo4j_graph_builder.py](backend/app/neo4j_graph_builder.py) vide la base, crée les index et charge les CSV en batch. Les nœuds reçoivent les attributs biologiques et les listes hiérarchiques `ec_hierarchy_labels`, les arêtes `:SIMILAR` stockent le poids de similarité.
- **Synchronisation MongoDB** : [backend/app/mongo_builder.py](backend/app/mongo_builder.py) consomme `nodes.csv` pour alimenter la collection MongoDB, en cohérence avec Neo4j.

## Algorithme de label propagation
- **Préparation** : la base Neo4j contient `ec_numbers` (labels explicites) et `ec_hierarchy_labels` (tous les niveaux intermédiaires). Un split aléatoire marque une fraction des protéines annotées comme jeu de test, le reste reste en train.
- **Propagation hiérarchique pondérée** : pour chaque nœud de test, [backend/app/label_propagation2.py](backend/app/label_propagation2.py) agrège les labels hiérarchiques des voisins d’entraînement via les arêtes `:SIMILAR`. Les poids des arêtes s’accumulent par code EC ; ils peuvent être normalisés et filtrés par seuil.
- **Prise de décision** : les scores hiérarchiques sont ordonnés, puis convertis en prédictions multi-label (au niveau hiérarchique complet ou partiel) selon un seuil configurable.
- **Évaluation** : scikit-learn calcule précision, rappel et F1 micro, ainsi que les mêmes métriques par profondeur EC (1 à 4). Les répétitions de splits fournissent des intervalles de performance et des exemples de prédictions sont journalisés pour inspection.