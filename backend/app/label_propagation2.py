import os
from collections import defaultdict

from neo4j import GraphDatabase
from tqdm import tqdm
import numpy as np
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics import precision_score, recall_score, f1_score

# -------------------------------------------------------------------
# Connexion Neo4j (mêmes variables d'env que neo4j_graph_builder.py)
# -------------------------------------------------------------------

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

driver = GraphDatabase.driver(uri, auth=(user, password))

# -------------------------------------------------------------------
# Fonctions utilitaires
# -------------------------------------------------------------------

def get_ec_level(ec: str) -> int:
    """
    Retourne le niveau hiérarchique d'un code EC (1 à 4).
    Ex: '1' -> 1, '1.2' -> 2, '1.2.3' -> 3, '1.2.3.4' -> 4.
    Les '-' sont ignorés.
    """
    if not ec:
        return 0
    parts = [p for p in ec.split('.') if p and p != '-']
    return len(parts)


# -------------------------------------------------------------------
# Split train / test
# -------------------------------------------------------------------

def setup_train_test_split(session, test_ratio: float = 0.2): # Ici on prend par défaut 20% des nœuds avec EC connus en test
    """
    Marque aléatoirement les noeuds comme 'train' ou 'test' dans Neo4j.
    On ne met en 'test' que des noeuds avec au moins un EC connu.
    """
    # Tout le monde en train
    session.run("MATCH (n:Protein) REMOVE n.subset")
    session.run("MATCH (n:Protein) SET n.subset = 'train'")

    # Sous-ensemble en test parmi ceux qui ont des EC connus
    query = """
    MATCH (n:Protein)
    WHERE n.ec_numbers IS NOT NULL AND size(n.ec_numbers) > 0
    WITH n, rand() AS r
    WHERE r < $ratio
    SET n.subset = 'test'
    RETURN count(n) AS test_count
    """
    result = session.run(query, ratio=test_ratio)
    count = result.single()["test_count"]
    print(f"   Split créé : {count} nœuds en TEST (le reste en TRAIN)")
    return count


# -------------------------------------------------------------------
# Propagation hiérarchique basée sur les poids des arêtes
# -------------------------------------------------------------------

def propagate_labels(session, min_weight_threshold: float = 0.0,
                     normalize_scores: bool = True,
                     score_threshold: float | None = 0.1):
    """
    Algorithme de type 'weighted voting' sur la hiérarchie EC.

    Pour chaque nœud TEST:
      - on regarde les voisins TRAIN via :SIMILAR (pondéré par r.weight)
      - on récupère neighbor.ec_hierarchy_labels (liste de codes hiérarchiques)
      - on somme les poids pour chaque code EC hiérarchique

    Retourne:
      - y_pred: liste de listes de codes EC prédits (pour évaluation)
      - y_true: liste de listes de codes EC réels (hiérarchiques)
      - predictions_detail: dict entry -> liste triée de {ec, score}
                            (scores éventuellement normalisés) pour le front.
    """
    query = """
    MATCH (target:Protein {subset: 'test'})
    MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'train'})
    WHERE r.weight > $min_weight

    // Déplier les EC hiérarchiques des voisins
    UNWIND neighbor.ec_hierarchy_labels AS ec

    // Cumuler les poids pour chaque code EC hiérarchique
    WITH target, ec, sum(r.weight) AS score
    ORDER BY score DESC

    // Regrouper par cible
    WITH target, collect({ec: ec, score: score}) AS predicted_list

    RETURN
      target.entry AS entry,
      target.ec_hierarchy_labels AS true_labels,
      predicted_list
    """

    result = session.run(query, min_weight=min_weight_threshold)

    y_pred = []
    y_true = []
    predictions_detail = {}

    for record in result:
        entry = record["entry"]
        true_labels = record["true_labels"] or []
        predicted_data = record["predicted_list"] or []

        if not predicted_data:
            # Aucun voisin train ou scores tous filtrés
            continue

        # Normalisation optionnelle pour interpréter les scores comme des "probas"
        if normalize_scores:
            total_score = sum(item["score"] for item in predicted_data)
            if total_score > 0:
                predicted_data = [
                    {"ec": item["ec"], "score": item["score"] / total_score}
                    for item in predicted_data
                ]

        # On garde la liste de détails pour le front
        predictions_detail[entry] = predicted_data

        if score_threshold is not None:
            best_predictions = [item["ec"] for item in predicted_data
                                if item["score"] >= score_threshold]
            if not best_predictions and predicted_data:
                best_predictions = [predicted_data[0]["ec"]]
        else:
            # fallback : tout garder
            best_predictions = [item["ec"] for item in predicted_data]

        y_true.append(true_labels)
        y_pred.append(best_predictions)

    return y_pred, y_true, predictions_detail


# -------------------------------------------------------------------
# Évaluation multi-label
# -------------------------------------------------------------------

def evaluate_metrics(y_pred, y_true):
    """
    Calcule precision / recall / f1 en multi-label avec scikit-learn.
    On binarise sur l'union des labels vrais + prédits.
    """
    if not y_true or not y_pred:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    mlb = MultiLabelBinarizer()
    mlb.fit(y_true + y_pred)

    y_true_bin = mlb.transform(y_true)
    y_pred_bin = mlb.transform(y_pred)

    return {
        "precision": precision_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        ),
        "recall": recall_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        ),
        "f1": f1_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        ),
    }


def evaluate_metrics_by_level(y_pred, y_true):
    """
    Calcule precision/recall/f1 séparément pour les niveaux 1, 2, 3, 4.
    Retourne un dict: {1: {...}, 2: {...}, 3: {...}, 4: {...}}
    """
    levels = {1, 2, 3, 4}
    results = {}

    for level in levels:
        # Filtrer les labels de ce niveau
        y_true_level = [
            [ec for ec in labels if get_ec_level(ec) == level]
            for labels in y_true
        ]
        y_pred_level = [
            [ec for ec in labels if get_ec_level(ec) == level]
            for labels in y_pred
        ]

        # S'il n'y a aucun label sur ce niveau, on renvoie des 0
        if all(len(lbls) == 0 for lbls in y_true_level) and all(
            len(lbls) == 0 for lbls in y_pred_level
        ):
            results[level] = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
            continue

        mlb = MultiLabelBinarizer()
        mlb.fit(y_true_level + y_pred_level)

        y_true_bin = mlb.transform(y_true_level)
        y_pred_bin = mlb.transform(y_pred_level)

        prec = precision_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        )
        rec = recall_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        )
        f1 = f1_score(
            y_true_bin, y_pred_bin, average="micro", zero_division=0
        )

        results[level] = {"precision": prec, "recall": rec, "f1": f1}

    return results


# -------------------------------------------------------------------
# Validation répétée de type "cross-validation"
# -------------------------------------------------------------------

def run_repeated_validation(session, n_repeats: int = 5, test_ratio: float = 0.2):
    """
    Effectue plusieurs splits aléatoires train/test, lance la propagation,
    et agrège les métriques.

    Ce n'est pas du k-fold strict (où chaque nœud est utilisé exactement
    une fois en test), mais une répétition de random splits.
    """
    print(f"\n🚀 Démarrage de la validation répétée ({n_repeats} itérations)...")

    scores = {"precision": [], "recall": [], "f1": []}
    # pour les niveaux 1..4
    level_scores = {1: {"precision": [], "recall": [], "f1": []},
                    2: {"precision": [], "recall": [], "f1": []},
                    3: {"precision": [], "recall": [], "f1": []},
                    4: {"precision": [], "recall": [], "f1": []}}

    for i in range(n_repeats):
        print(f"\n--- Repeat {i+1}/{n_repeats} ---")

        test_count = setup_train_test_split(session, test_ratio=test_ratio)
        if test_count == 0:
            print("⚠️ Aucun nœud test disponible pour ce split, on skip.")
            continue

        y_pred, y_true, predictions_detail = propagate_labels(session, score_threshold=0.1)

        if not y_pred:
            print("⚠️ Aucune prédiction effectuée pour ce split.")
            continue

        # Afficher quelques exemples du set de test pour ce split
        show_test_examples(session, predictions_detail, k=5)

        # métriques globales (tous niveaux confondus)
        fold_metrics = evaluate_metrics(y_pred, y_true)
        scores["precision"].append(fold_metrics["precision"])
        scores["recall"].append(fold_metrics["recall"])
        scores["f1"].append(fold_metrics["f1"])

        print(f"   Global - Précision: {fold_metrics['precision']:.4f}")
        print(f"            Rappel:    {fold_metrics['recall']:.4f}")
        print(f"            F1-Score:  {fold_metrics['f1']:.4f}")

        # métriques par niveau
        fold_by_level = evaluate_metrics_by_level(y_pred, y_true)
        for level, m in fold_by_level.items():
            level_scores[level]["precision"].append(m["precision"])
            level_scores[level]["recall"].append(m["recall"])
            level_scores[level]["f1"].append(m["f1"])
            print(
                f"   Niveau {level} - P: {m['precision']:.4f} "
                f"R: {m['recall']:.4f} F1: {m['f1']:.4f}"
            )

    if scores["precision"]:
        print("\n📊 Résultats Moyens :")
        print(f"Moyenne Précision : {np.mean(scores['precision']):.4f}")
        print(f"Moyenne Rappel    : {np.mean(scores['recall']):.4f}")
        print(f"Moyenne F1        : {np.mean(scores['f1']):.4f}")
    else:
        print("\n⚠️ Impossible de calculer des moyennes (aucune prédiction valide).")

    print("\n📊 Résultats Moyens par niveau :")
    for level in sorted(level_scores.keys()):
        if level_scores[level]["precision"]:
            print(
                f" Niveau {level} - "
                f"P: {np.mean(level_scores[level]['precision']):.4f} "
                f"R: {np.mean(level_scores[level]['recall']):.4f} "
                f"F1: {np.mean(level_scores[level]['f1']):.4f}"
            )


# -------------------------------------------------------------------
# Prédiction finale pour tous les noeuds et stockage dans Neo4j + MongoDB
# -------------------------------------------------------------------

def compute_final_predictions_and_store(
    session,
    min_weight_threshold: float = 0.0,
    normalize_scores: bool = True,
    batch_size: int = 500,
):
    """
    1. Considère tous les noeuds ayant des EC connus comme "labeled".
    2. Pour les noeuds SANS EC (unlabeled), agrège les votes depuis les voisins labeled.
    3. Met à jour directement ec_numbers dans Neo4j et MongoDB pour les protéines sans EC.
    """
    from pymongo import MongoClient
    import dotenv
    
    dotenv.load_dotenv()
    
    # Connexion MongoDB
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME")

    print("\n🔎 Calcul des prédictions finales pour les noeuds sans EC...")

    # On marque explicitement les noeuds contenant des EC comme 'labeled'
    session.run("MATCH (n:Protein) REMOVE n.subset")
    session.run(
        """
        MATCH (n:Protein)
        SET n.subset = CASE
            WHEN n.ec_numbers IS NOT NULL AND size(n.ec_numbers) > 0
            THEN 'labeled' ELSE 'unlabeled' END
        """
    )

    # Requête: UNIQUEMENT pour les noeuds unlabeled, on agrège les infos des voisins labellisés
    query = """
    MATCH (target:Protein {subset: 'unlabeled'})
    MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'labeled'})
    WHERE r.weight > $min_weight

    UNWIND neighbor.ec_numbers AS ec

    WITH target, ec, sum(r.weight) AS score
    ORDER BY score DESC

    WITH target, collect({ec: ec, score: score}) AS predicted_list

    RETURN
        target.entry AS entry,
        predicted_list
    """

    result = session.run(
        query,
        min_weight=min_weight_threshold,
    )

    # On prépare les mises à jour
    updates = []

    for record in result:
        entry = record["entry"]
        predicted_data = record["predicted_list"] or []

        if normalize_scores and predicted_data:
            total_score = sum(item["score"] for item in predicted_data)
            if total_score > 0:
                predicted_data = [
                    {"ec": item["ec"], "score": item["score"] / total_score}
                    for item in predicted_data
                ]

        # Filtrer uniquement les EC complets (niveau 4 : X.X.X.X)
        full_ec_predictions = [
            p for p in predicted_data if get_ec_level(p["ec"]) == 4
        ]

        # Prendre le meilleur EC (score le plus élevé)
        if full_ec_predictions:
            best_ec = full_ec_predictions[0]["ec"]
            updates.append({
                "entry": entry,
                "ec_numbers": [best_ec],
            })

    print(f"   Prédictions calculées pour {len(updates)} nœuds sans EC.")

    if not updates:
        print("   Aucune prédiction à appliquer.")
        return

    # --- Mise à jour Neo4j ---
    def update_batch_neo4j(tx, batch):
        tx.run(
            """
            UNWIND $batch AS update
            MATCH (p:Protein {entry: update.entry})
            WHERE p.ec_numbers IS NULL OR size(p.ec_numbers) = 0
            SET p.ec_numbers = update.ec_numbers
            """,
            batch=batch,
        )

    total_updated_neo4j = 0
    for i in tqdm(range(0, len(updates), batch_size), desc="Mise à jour Neo4j"):
        batch = updates[i : i + batch_size]
        session.execute_write(update_batch_neo4j, batch)
        total_updated_neo4j += len(batch)

    print(f"✅ {total_updated_neo4j} nœuds mis à jour dans Neo4j (ec_numbers)")

    # --- Mise à jour MongoDB ---
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        total_updated_mongo = 0
        for update in tqdm(updates, desc="Mise à jour MongoDB"):
            result = collection.update_one(
                {
                    "_id": update["entry"],
                    "$or": [
                        {"annotations.ec_numbers": {"$exists": False}},
                        {"annotations.ec_numbers": []},
                        {"annotations.ec_numbers": None}
                    ]
                },
                {"$set": {"annotations.ec_numbers": update["ec_numbers"]}}
            )
            if result.modified_count > 0:
                total_updated_mongo += 1
        
        client.close()
        print(f"✅ {total_updated_mongo} documents mis à jour dans MongoDB (annotations.ec_numbers)")
        
    except Exception as e:
        print(f"❌ Erreur MongoDB: {e}")
    
    # Afficher quelques exemples
    show_updated_examples(session, updates[:5])


def show_updated_examples(session, updates, k: int = 5):
    """
    Affiche quelques exemples de noeuds qui ont été mis à jour avec des EC prédits.
    """
    print(f"\n🔍 Exemples de noeuds mis à jour avec EC prédit :")
    
    for update in updates[:k]:
        entry = update["entry"]
        ec_numbers = update["ec_numbers"]
        print(f"   - Entry: {entry}")
        print(f"     EC prédit: {ec_numbers}")
        print()


# -------------------------------------------------------------------
# Affichage des exemples de test
# -------------------------------------------------------------------

def show_test_examples(session, predictions_detail, k: int = 5):
    """
    Affiche k exemples de noeuds du set de test avec :
      - Entry
      - EC hiérarchiques vrais
      - quelques labels prédits avec leurs scores
    """
    # Récupérer les entrées test concernées (celles pour lesquelles on a des prédictions)
    entries = list(predictions_detail.keys())[:k]
    if not entries:
        print("   (Aucun exemple à afficher, pas de prédictions)")
        return

    # Récupérer les infos de base depuis Neo4j
    query = """
    MATCH (p:Protein)
    WHERE p.entry IN $entries
    RETURN p.entry AS entry,
           p.ec_numbers AS ec_numbers,
           p.ec_hierarchy_labels AS ec_hierarchy_labels
    """
    result = session.run(query, entries=entries)
    entry_to_info = {r["entry"]: r for r in result}

    print("\n   🔍 Exemples de noeuds TEST (vrais vs prédits) :")
    for entry in entries:
        info = entry_to_info.get(entry, {})
        true_ec_numbers = info.get("ec_numbers", [])
        true_hier = info.get("ec_hierarchy_labels", [])

        preds = predictions_detail.get(entry, [])
        print(f"   - Entry: {entry}")
        print(f"     True EC numbers: {true_ec_numbers}")
        print(f"     True hierarchy : {true_hier}")

        # Afficher quelques labels prédits avec leurs scores
        for item in preds[:5]:
            ec = item["ec"]
            score = item["score"]
            level = get_ec_level(ec)
            print(f"       Predicted: {ec} (level {level}) score={score:.3f}")
        print()


# -------------------------------------------------------------------
# API pour le Frontend
# -------------------------------------------------------------------

def run_validation_for_frontend(n_repeats: int = 5, test_ratio: float = 0.2):
    """
    Exécute la validation répétée et retourne les résultats pour le frontend.
    Inclut désormais des exemples détaillés de la dernière itération.
    """
    with driver.session(database=database_name) as session:
        scores = {"precision": [], "recall": [], "f1": []}
        level_scores = {
            1: {"precision": [], "recall": [], "f1": []},
            2: {"precision": [], "recall": [], "f1": []},
            3: {"precision": [], "recall": [], "f1": []},
            4: {"precision": [], "recall": [], "f1": []}
        }
        
        # Pour stocker les détails de la dernière itération
        last_iteration_details = []

        for i in range(n_repeats):
            test_count = setup_train_test_split(session, test_ratio=test_ratio)
            if test_count == 0:
                continue

            # On récupère predictions_detail ici
            y_pred, y_true, predictions_detail = propagate_labels(session, score_threshold=0.1)

            if not y_pred:
                continue

            # Stocker les détails pour la dernière itération seulement (pour affichage frontend)
            # On doit réassocier entry -> true_labels car predictions_detail ne contient que les preds
            if i == n_repeats - 1:
                # Récupération des vrais labels pour les entrées prédites
                entries_list = list(predictions_detail.keys())
                # On le fait en batch ou on suppose que l'ordre de y_true correspond à l'ordre d'insertion ?
                # Le plus sûr est de refaire une petite passe ou de modifier propagate_labels pour renvoyer un dict structuré.
                # Pour faire simple sans casser propagate_labels, on refait une petite query pour ces entrées :
                query_details = """
                MATCH (p:Protein)
                WHERE p.entry IN $entries
                RETURN p.entry AS entry, p.ec_numbers AS true_ec
                """
                res = session.run(query_details, entries=entries_list[:10]) # On ne garde que 10 exemples
                
                for record in res:
                    entry = record["entry"]
                    true_ec = record["true_ec"] if record["true_ec"] else []
                    preds = predictions_detail.get(entry, [])
                    last_iteration_details.append({
                        "entry": entry,
                        "true_ec": true_ec,
                        "predictions": preds # liste de {ec, score}
                    })

            # Métriques globales
            fold_metrics = evaluate_metrics(y_pred, y_true)
            scores["precision"].append(fold_metrics["precision"])
            scores["recall"].append(fold_metrics["recall"])
            scores["f1"].append(fold_metrics["f1"])

            # Métriques par niveau
            fold_by_level = evaluate_metrics_by_level(y_pred, y_true)
            for level, m in fold_by_level.items():
                level_scores[level]["precision"].append(m["precision"])
                level_scores[level]["recall"].append(m["recall"])
                level_scores[level]["f1"].append(m["f1"])

        # Moyennes
        global_metrics = {
            "precision": float(np.mean(scores["precision"])) if scores["precision"] else 0.0,
            "recall": float(np.mean(scores["recall"])) if scores["recall"] else 0.0,
            "f1": float(np.mean(scores["f1"])) if scores["f1"] else 0.0,
        }

        level_metrics = {}
        for level in [1, 2, 3, 4]:
            level_metrics[level] = {
                "precision": float(np.mean(level_scores[level]["precision"])) if level_scores[level]["precision"] else 0.0,
                "recall": float(np.mean(level_scores[level]["recall"])) if level_scores[level]["recall"] else 0.0,
                "f1": float(np.mean(level_scores[level]["f1"])) if level_scores[level]["f1"] else 0.0,
            }

        return {
            "global_metrics": global_metrics,
            "level_metrics": level_metrics,
            "n_repeats": n_repeats,
            "test_ratio": test_ratio,
            "detailed_examples": last_iteration_details # AJOUT ICI
        }


def run_prediction_for_frontend(min_weight_threshold: float = 0.0):
    """
    Exécute la prédiction et mise à jour des EC pour les protéines sans EC.
    
    Returns:
        dict avec:
            - total_updated_neo4j: int
            - total_updated_mongo: int
            - examples: list de {"entry": str, "ec_numbers": list}
    """
    from pymongo import MongoClient
    import dotenv
    
    dotenv.load_dotenv()
    
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME")
    COLLECTION_NAME = os.getenv("COLLECTION_NAME")

    with driver.session(database=database_name) as session:
        # Marquer labeled/unlabeled
        session.run("MATCH (n:Protein) REMOVE n.subset")
        session.run(
            """
            MATCH (n:Protein)
            SET n.subset = CASE
                WHEN n.ec_numbers IS NOT NULL AND size(n.ec_numbers) > 0
                THEN 'labeled' ELSE 'unlabeled' END
            """
        )

        # Requête pour les noeuds unlabeled
        query = """
        MATCH (target:Protein {subset: 'unlabeled'})
        MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'labeled'})
        WHERE r.weight > $min_weight

        UNWIND neighbor.ec_numbers AS ec

        WITH target, ec, sum(r.weight) AS score
        ORDER BY score DESC

        WITH target, collect({ec: ec, score: score}) AS predicted_list

        RETURN
            target.entry AS entry,
            predicted_list
        """

        result = session.run(query, min_weight=min_weight_threshold)

        updates = []
        for record in result:
            entry = record["entry"]
            predicted_data = record["predicted_list"] or []

            # Normalisation
            if predicted_data:
                total_score = sum(item["score"] for item in predicted_data)
                if total_score > 0:
                    predicted_data = [
                        {"ec": item["ec"], "score": item["score"] / total_score}
                        for item in predicted_data
                    ]

            # Filtrer EC niveau 4
            full_ec_predictions = [
                p for p in predicted_data if get_ec_level(p["ec"]) == 4
            ]

            if full_ec_predictions:
                best_ec = full_ec_predictions[0]["ec"]
                updates.append({
                    "entry": entry,
                    "ec_numbers": [best_ec],
                })

        if not updates:
            return {
                "total_updated_neo4j": 0,
                "total_updated_mongo": 0,
                "examples": [],
            }

        # Mise à jour Neo4j
        def update_batch_neo4j(tx, batch):
            tx.run(
                """
                UNWIND $batch AS update
                MATCH (p:Protein {entry: update.entry})
                WHERE p.ec_numbers IS NULL OR size(p.ec_numbers) = 0
                SET p.ec_numbers = update.ec_numbers
                """,
                batch=batch,
            )

        batch_size = 500
        total_updated_neo4j = 0
        for i in range(0, len(updates), batch_size):
            batch = updates[i : i + batch_size]
            session.execute_write(update_batch_neo4j, batch)
            total_updated_neo4j += len(batch)

        # Mise à jour MongoDB
        total_updated_mongo = 0
        try:
            client = MongoClient(MONGO_URI)
            db = client[DB_NAME]
            collection = db[COLLECTION_NAME]
            
            for update in updates:
                result = collection.update_one(
                    {
                        "_id": update["entry"],
                        "$or": [
                            {"annotations.ec_numbers": {"$exists": False}},
                            {"annotations.ec_numbers": []},
                            {"annotations.ec_numbers": None}
                        ]
                    },
                    {"$set": {"annotations.ec_numbers": update["ec_numbers"]}}
                )
                if result.modified_count > 0:
                    total_updated_mongo += 1
            
            client.close()
        except Exception as e:
            print(f"Erreur MongoDB: {e}")

        return {
            "total_updated_neo4j": total_updated_neo4j,
            "total_updated_mongo": total_updated_mongo,
            "examples": updates[:10],  # 10 premiers exemples
        }


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

if __name__ == "__main__":
    with driver.session(database=database_name) as session:
        # Option 1 : validation répétée (pour évaluer les performances)
        run_repeated_validation(session, n_repeats=5, test_ratio=0.2)

        # Option 2 : prédictions finales et mise à jour ec_numbers dans Neo4j + MongoDB
        compute_final_predictions_and_store(
            session,
            min_weight_threshold=0.0,
            normalize_scores=True,
        )

    driver.close()