# Projet


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


## Algorithme de label propagation
Le script lit un fichier de protéines contenant leurs domaines InterPro et leurs numéros EC, puis construit automatiquement un graphe où chaque protéine est un nœud relié aux autres selon la similarité Jaccard-IDF de leurs ensembles de domaines. À partir de ce graphe, il identifie les protéines annotées par un EC, encode ces labels sous forme one-hot, puis masque aléatoirement une partie de ces annotations pour créer un ensemble de test. L’algorithme de **Label Propagation** est ensuite appliqué : les labels connus (EC) sont fixés sur les nœuds “annotés”, et les probabilités de labels se diffusent dans le graphe via une normalisation symétrique de la matrice d’adjacence, jusqu’à convergence. Le script compare alors, pour les protéines dont l’EC a été masqué, la prédiction obtenue par propagation à la vérité initiale, calculant une accuracy stricte et une top-3 accuracy. Enfin, il affiche plusieurs exemples concrets de prédictions (EC vrai, EC prédit, probabilité), fournissant une évaluation qualitative du modèle sur les données.