# Protein Database Explorer - Documentation

## Aperçu du projet

**Protein Database Explorer** est une application web complète permettant de stocker, rechercher, analyser et visualiser des données protéiques à l'aide de bases de données NoSQL (MongoDB et Neo4j). L'application se distingue par son système de **propagation de labels configurable** permettant de prédire les fonctions enzymatiques (numéros EC) des protéines non annotées selon plusieurs stratégies algorithmiques.

### Fonctionnalités principales
- 🔍 **Recherche avancée** dans MongoDB avec auto-complétion en temps réel
- 📊 **Visualisation interactive** des réseaux de similarité dans Neo4j (zoom, déplacement, physique des nœuds)
- 🏷️ **Propagation automatique** des annotations EC avec 3 stratégies (Baseline, Consensus, Cascade)
- 📈 **Tableau de bord statistique** avec historiques et graphiques comparatifs
- ➕ **CRUD complet** (Ajout/Suppression synchronisée MongoDB/Neo4j)
- 🧪 **Validation du modèle** via Cross-Validation configurable


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
```text
pandas
neo4j
pymongo
python-dotenv
tqdm
streamlit
streamlit-searchbox
streamlit-agraph  # Nécessaire pour la visualisation du graphe
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

#### Chargement des données initiales
1. Placer votre fichier `uniprot.tsv` dans `backend/data/raw/`
2. Exécuter les scripts de remplissage des bases de données :

```bash
python backend/app/graph_builder.py        # Génération des CSV (nodes/edges)
python backend/app/neo4j_graph_builder.py  # Import Neo4j
python backend/app/mongo_builder.py        # Import MongoDB
```

### 4. Lancement de l'application

```bash
streamlit run frontend/app/pages/front.py
```
L'application sera accessible à l'adresse : http://localhost:8501

---

## Interface principale

### 1. Recherche de protéines
- **Barre de recherche centrale** : Auto-complétion en temps réel  
- **Filtres avancés** dans la sidebar :
  - Recherche par mot-clé  
  - Filtres EC (logique AND/OR avancée : ajout dynamique de champs)  
  - Filtres InterPro  
  - Longueur de séquence  
  - Organisme  

### 2. Visualisation des graphes
- Cliquez sur **"Afficher le graphe"** dans un résultat  
- **Paramètres ajustables** :
  - `k` : Nombre de voisins directs (Niveau 1)
  - `m` : Nombre de voisins de voisins (Niveau 2)
- **Légende des couleurs** :
  - 🔴 Rouge : Protéine centrale (Target)
  - 🔵 Bleu : Voisins directs  
  - 🟢 Vert : Voisins de niveau 2  
- **Interactivité** : Les nœuds sont cliquables et déplaçables.

### 3. Gestion des données (CRUD)
- **Ajouter une protéine** : Formulaire modal avec validation des champs.
- **Supprimer une protéine** : Bouton dans les détails de la protéine (avec confirmation).  
- **Synchronisation** : Toute modification est répercutée instantanément dans MongoDB et Neo4j.

### 4. Statistiques
- Accédez aux statistiques globales en bas de page.
- **Snapshots** : Calculez et stockez l'état de la base à un instant T.
- **Visualisation** : Graphiques camemberts (Pie Charts) pour les ratios Labellisées/Isolées.

### 5. Propagation de labels (Onglet dédié)
L'interface propose 3 onglets pour gérer l'IA :
1.  **Explications** : Détail des concepts.
2.  **Validation** : Lancer une Cross-Validation sur le jeu de données actuel pour estimer la précision.
3.  **Prédiction (Production)** : Appliquer les calculs pour écrire les nouvelles annotations en base.

**Sélecteur de stratégie :**
- **Baseline (Weighted Voting)** : Vote pondéré standard (rapide).
- **Consensus (Fallback)** : Tente le niveau 4, se replie sur le niveau 3 si incertain (robuste).
- **Cascade (Multi-Run)** : Propagation itérative par niveaux successifs (maximise le rappel).

---

## Structure du Backend

```text
backend/app/
├── mongo_queries.py                  # Moteur de recherche MongoDB
├── neo4j_query.py                    # Extraction de sous-graphes pour la viz
├── label_propagation_with_hierarchy.py # Cœur algorithmique (Baseline, Consensus, Cascade)
├── graph_builder.py                  # ETL : Parsing TSV -> CSV
├── neo4j_graph_builder.py            # ETL : Chargement Batch Neo4j
├── mongo_builder.py                  # ETL : Chargement MongoDB
├── add_protein.py                    # Logique d'ajout (CRUD)
├── delete_protein.py                 # Logique de suppression (CRUD)
├── stats.py                          # Calcul des métriques globales
└── mongo_reset.py                    # Utilitaires de reset
```

---

## Algorithme de label propagation

L'algorithme repose sur l'hypothèse que des protéines partageant des domaines fonctionnels (InterPro) ont probablement la même fonction enzymatique (EC).

1.  **Construction du Graphe** : Les arêtes `:SIMILAR` sont pondérées par l'indice de Jaccard sur les domaines InterPro.
2.  **Stratégies implémentées** :
    *   **Baseline** : Pour une protéine cible, on additionne les poids des voisins pour chaque label EC. Le label avec le score le plus élevé l'emporte, peu importe son niveau (tous niveaux confondus).
    *   **Consensus** : Vérifie la confiance du meilleur candidat. Si < seuil, on agrège les scores au niveau hiérarchique supérieur (ex: 1.14.14 -> 1.14) jusqu'à trouver un consensus fiable.
    *   **Cascade** : Exécute 4 passes. Passe 1 : Prédit uniquement les EC niveau 4 très sûrs. Ces nouvelles prédictions deviennent des sources ("Training set") pour la Passe 2 (niveau 3), etc. Cela permet de propager l'information plus loin dans le graphe.

---

## Setup MongoDB (Mémo)

### Sur Linux
```bash
# Installation (exemple Ubuntu)
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | sudo gpg --dearmor -o /usr/share/keyrings/mongodb.gpg
echo "deb [ arch=amd64 signed-by=/usr/share/keyrings/mongodb.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
```

### Lancement local (sans service)
Dans un terminal :
```bash
mkdir mongobin
cd mongobin
mongod --dbpath .
```