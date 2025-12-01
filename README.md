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