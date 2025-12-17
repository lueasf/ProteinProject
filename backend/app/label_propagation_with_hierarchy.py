import os
from collections import defaultdict
import time
import dotenv
import numpy as np
from tqdm import tqdm

from neo4j import GraphDatabase
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.metrics import precision_score, recall_score, f1_score
from pymongo import MongoClient, UpdateOne

# Assure-toi que ce fichier existe bien dans ton dossier, sinon copie la fonction expand_ec ici
try:
    from graph_builder import expand_ec
except ImportError:
    # Fallback si l'import échoue
    def expand_ec(ec_list):
        if not ec_list: return []
        expanded = set()
        for ec in ec_list:
            parts = ec.split('.')
            for i in range(1, len(parts) + 1):
                expanded.add('.'.join(parts[:i]))
        return list(expanded)

# -------------------------------------------------------------------
# Configuration & Connexion
# -------------------------------------------------------------------

dotenv.load_dotenv()

uri = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "NoSQLProject")
database_name = os.getenv("NEO4J_DATABASE_NAME", "project")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "prot_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "proteins")

driver = GraphDatabase.driver(uri, auth=(user, password))

# -------------------------------------------------------------------
# Utilitaires
# -------------------------------------------------------------------

def get_ec_level(ec: str) -> int:
    """Retourne le niveau hiérarchique d'un code EC (1 à 4)."""
    if not ec: return 0
    parts = [p for p in ec.split('.') if p and p != '-']
    return len(parts)

def setup_train_test_split(session, test_ratio: float = 0.2):
    """Prépare le graphe pour la validation (subset='train' vs 'test')"""
    session.run("MATCH (n:Protein) REMOVE n.subset")
    session.run("MATCH (n:Protein) SET n.subset = 'train'") 

    query = """
    MATCH (n:Protein)
    WHERE n.ec_numbers IS NOT NULL AND size(n.ec_numbers) > 0
    WITH n, rand() AS r
    WHERE r < $ratio
    SET n.subset = 'test'
    RETURN count(n) AS test_count
    """
    result = session.run(query, ratio=test_ratio)
    # Gestion sécurisée si le résultat est vide
    record = result.single()
    return record["test_count"] if record else 0

# ===================================================================
# PARTIE 1 : VALIDATION (Test des stratégies)
# ===================================================================

# --- Stratégie 1 : BASELINE (Vote simple) ---
def propagate_labels_baseline(session, min_weight_threshold: float = 0.0, score_threshold: float = 0.1):
    query = """
    MATCH (target:Protein {subset: 'test'})
    MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'train'})
    WHERE r.weight > $min_weight
    UNWIND neighbor.ec_hierarchy_labels AS ec
    WITH target, ec, sum(r.weight) AS score
    ORDER BY score DESC
    WITH target, collect({ec: ec, score: score}) AS predicted_list
    RETURN target.entry AS entry, target.ec_hierarchy_labels AS true_labels, predicted_list
    """
    result = session.run(query, min_weight=min_weight_threshold)
    y_pred, y_true = [], []
    details = {} 

    for record in result:
        entry = record["entry"]
        true_labels = record["true_labels"] or []
        predicted_data = record["predicted_list"] or []
        
        # Normalisation
        if predicted_data:
            total = sum(p["score"] for p in predicted_data)
            if total > 0:
                for p in predicted_data: p["score"] /= total
        
        details[entry] = predicted_data # Pour le front
        
        # Sélection
        best_preds = [item["ec"] for item in predicted_data if item["score"] >= score_threshold]
        if not best_preds and predicted_data: best_preds = [predicted_data[0]["ec"]]
        
        y_true.append(true_labels)
        y_pred.append(best_preds)
        
    return y_pred, y_true, details

# --- Stratégie 2 : CONSENSUS (Fallback intelligent) ---
def propagate_labels_consensus(session, min_weight_threshold: float = 0.0, confidence_threshold: float = 0.6):
    query = """
    MATCH (target:Protein {subset: 'test'})
    MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'train'})
    WHERE r.weight > $min_weight
    UNWIND neighbor.ec_hierarchy_labels AS ec
    WITH target, ec, sum(r.weight) AS score
    ORDER BY score DESC
    WITH target, collect({ec: ec, score: score}) AS predicted_list
    RETURN target.entry AS entry, target.ec_hierarchy_labels AS true_labels, predicted_list
    """
    result = session.run(query, min_weight=min_weight_threshold)
    y_pred, y_true = [], []
    details = {} 

    for record in result:
        entry = record["entry"]
        true_labels = record["true_labels"] or []
        raw_preds = record["predicted_list"] or []
        
        if not raw_preds: continue

        candidates_by_lvl = defaultdict(list)
        total_by_lvl = defaultdict(float)
        for item in raw_preds:
            lvl = get_ec_level(item["ec"])
            candidates_by_lvl[lvl].append(item)
            total_by_lvl[lvl] += item["score"]

        selected = None
        final_conf = 0.0

        for lvl in [4, 3, 2, 1]:
            cands = candidates_by_lvl[lvl]
            total = total_by_lvl[lvl]
            if not cands or total == 0: continue
            
            best = cands[0]
            conf = best["score"] / total
            if conf >= confidence_threshold:
                selected = best["ec"]
                final_conf = conf
                break
        
        y_true.append(true_labels)
        y_pred.append([selected] if selected else [])
        
        # Détail simplifié pour le front
        if selected:
            details[entry] = [{"ec": selected, "score": final_conf}]
        else:
            details[entry] = []

    return y_pred, y_true, details

# --- Stratégie 3 : CASCADE (Multi-passes simulées) ---
def run_cascade_experiment(session, min_weight_threshold: float = 0.0, confidence_threshold: float = 0.85):
    # Setup simulation
    session.run("MATCH (n:Protein) SET n.temp_train = (n.subset = 'train')")
    session.run("MATCH (n:Protein) REMOVE n.temp_ec_label")

    resolved_nodes = set()
    y_pred_final = {} 
    details_temp = {}

    # Boucle 4 -> 1
    for level in [4, 3, 2, 1]:
        query = """
        MATCH (target:Protein {{subset: 'test'}})
        WHERE NOT target.entry IN $resolved
        MATCH (target)-[r:SIMILAR]-(neighbor:Protein)
        WHERE (neighbor.subset = 'train' OR neighbor.temp_train = true) AND r.weight > $min_weight
        WITH target, neighbor, r,
             CASE WHEN neighbor.subset = 'train' THEN neighbor.ec_hierarchy_labels ELSE [neighbor.temp_ec_label] END as n_labels
        UNWIND n_labels as ec
        WITH target, ec, r WHERE size(split(replace(ec, '-', ''), '.')) >= $level
        WITH target, r, reduce(s = '', i IN range(0, $level-1) | s + (CASE WHEN i>0 THEN '.' ELSE '' END) + split(replace(ec, '-', ''), '.')[i]) as ec_trunc
        WITH target, ec_trunc, sum(r.weight) as score ORDER BY score DESC
        WITH target, collect({{'ec': ec_trunc, 'score': score}}) as cands, sum(score) as total
        RETURN target.entry as entry, cands, total
        """
        result = session.run(query, min_weight=min_weight_threshold, resolved=list(resolved_nodes))
        
        new_batch = []
        for record in result:
            entry = record["entry"]
            cands = record["cands"]
            total = record["total"]
            if not cands or total == 0: continue
            
            best = cands[0]
            conf = best["score"] / total
            
            if conf >= confidence_threshold:
                y_pred_final[entry] = best["ec"]
                resolved_nodes.add(entry)
                new_batch.append({'entry': entry, 'label': best["ec"]})
                details_temp[entry] = [{"ec": best["ec"], "score": conf}]

        if new_batch:
            session.run("UNWIND $b as row MATCH (n:Protein {entry:row.entry}) SET n.temp_train=true, n.temp_ec_label=row.label", b=new_batch)

    # Nettoyage
    session.run("MATCH (n:Protein) REMOVE n.temp_train, n.temp_ec_label")

    # Reconstruction y_true
    entries = list(y_pred_final.keys())
    y_pred, y_true = [], []
    final_details = {}
    
    if entries:
        res = session.run("MATCH (n:Protein) WHERE n.entry IN $ids RETURN n.entry as e, n.ec_hierarchy_labels as t", ids=entries)
        truth_map = {r['e']: r['t'] for r in res}
        for e in entries:
            y_pred.append([y_pred_final[e]])
            y_true.append(truth_map.get(e, []))
            final_details[e] = details_temp.get(e, [])
            
    return y_pred, y_true, final_details

# --- Metrics ---
def evaluate_metrics(y_pred, y_true):
    if not y_true or not y_pred: return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    mlb = MultiLabelBinarizer()
    mlb.fit(y_true + y_pred)
    yb_true = mlb.transform(y_true)
    yb_pred = mlb.transform(y_pred)
    return {
        "precision": precision_score(yb_true, yb_pred, average="micro", zero_division=0),
        "recall": recall_score(yb_true, yb_pred, average="micro", zero_division=0),
        "f1": f1_score(yb_true, yb_pred, average="micro", zero_division=0),
    }

def evaluate_metrics_by_level(y_pred, y_true):
    levels = {1, 2, 3, 4}
    results = {}
    for lvl in levels:
        yt_l = [[e for e in labs if get_ec_level(e) == lvl] for labs in y_true]
        yp_l = [[e for e in labs if get_ec_level(e) == lvl] for labs in y_pred]
        
        # Skip empty
        if all(not x for x in yt_l) and all(not x for x in yp_l):
            results[lvl] = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
            continue

        mlb = MultiLabelBinarizer()
        mlb.fit(yt_l + yp_l)
        results[lvl] = {
            "precision": precision_score(mlb.transform(yt_l), mlb.transform(yp_l), average="micro", zero_division=0),
            "recall": recall_score(mlb.transform(yt_l), mlb.transform(yp_l), average="micro", zero_division=0),
            "f1": f1_score(mlb.transform(yt_l), mlb.transform(yp_l), average="micro", zero_division=0),
        }
    return results

# --- CONTROLLEUR VALIDATION (Appelé par le Front) ---
def run_validation_for_frontend(n_repeats: int = 3, test_ratio: float = 0.2, strategy: str = "baseline"):
    with driver.session(database=database_name) as session:
        scores = defaultdict(list)
        lvl_scores = {1: defaultdict(list), 2: defaultdict(list), 3: defaultdict(list), 4: defaultdict(list)}
        examples_out = []

        for i in range(n_repeats):
            cnt = setup_train_test_split(session, test_ratio)
            if cnt == 0: continue

            if strategy == "consensus":
                yp, yt, dets = propagate_labels_consensus(session, confidence_threshold=0.6)
            elif strategy == "cascade":
                yp, yt, dets = run_cascade_experiment(session, confidence_threshold=0.85)
            else: # baseline
                yp, yt, dets = propagate_labels_baseline(session)

            if not yp: continue

            # Metrics
            m = evaluate_metrics(yp, yt)
            scores["p"].append(m["precision"])
            scores["r"].append(m["recall"])
            scores["f1"].append(m["f1"])

            ml = evaluate_metrics_by_level(yp, yt)
            for l, v in ml.items():
                lvl_scores[l]["p"].append(v["precision"])
                lvl_scores[l]["r"].append(v["recall"])
                lvl_scores[l]["f1"].append(v["f1"])
            
            # Capture examples on last run
            if i == n_repeats - 1:
                keys = list(dets.keys())[:15]
                if keys:
                    res = session.run("MATCH (p:Protein) WHERE p.entry IN $ids RETURN p.entry as e, p.ec_numbers as ec", ids=keys)
                    for r in res:
                        examples_out.append({
                            "entry": r["e"],
                            "true_ec": r["ec"],
                            "predictions": dets.get(r["e"], [])
                        })

        # Aggregation
        glob = {k: (np.mean(v) if v else 0.0) for k, v in scores.items()}
        # Rename keys for front
        glob_clean = {"precision": glob.get("p",0), "recall": glob.get("r",0), "f1": glob.get("f1",0)}
        
        lvl_clean = {}
        for l in [1,2,3,4]:
            d = lvl_scores[l]
            lvl_clean[l] = {
                "precision": np.mean(d["p"]) if d["p"] else 0.0,
                "recall": np.mean(d["r"]) if d["r"] else 0.0,
                "f1": np.mean(d["f1"]) if d["f1"] else 0.0
            }

        return {
            "global_metrics": glob_clean,
            "level_metrics": lvl_clean,
            "n_repeats": n_repeats,
            "detailed_examples": examples_out
        }

# ===================================================================
# PARTIE 2 : PROPAGATION RÉELLE (Mise à jour Base de données)
# ===================================================================

def compute_cascade_prediction_real(session, min_weight: float, conf_thresh: float):
    """Logique Cascade sur données réelles (Unlabeled -> Labeled)"""
    print(f"\n🌊 [CASCADE REAL] Start (Seuil: {conf_thresh})")
    
    # Init : Marquage des connus
    session.run("MATCH (n:Protein) REMOVE n.temp_known, n.temp_ec")
    session.run("MATCH (n:Protein) WHERE size(n.ec_numbers)>0 SET n.temp_known=true")
    
    updates = []
    
    for level in [4, 3, 2, 1]:
        print(f"   ... Level {level}")
        query = """
        MATCH (target:Protein)
        WHERE (target.ec_numbers IS NULL OR size(target.ec_numbers)=0) AND target.temp_known IS NULL
        MATCH (target)-[r:SIMILAR]-(neighbor:Protein)
        WHERE neighbor.temp_known = true AND r.weight > $mw
        WITH target, neighbor, r,
             CASE WHEN neighbor.temp_ec IS NOT NULL THEN [neighbor.temp_ec] ELSE neighbor.ec_hierarchy_labels END as n_labels
        UNWIND n_labels as ec
        WITH target, ec, r WHERE size(split(replace(ec, '-', ''), '.')) >= $level
        WITH target, r, reduce(s='', i IN range(0,$level-1)|s+(CASE WHEN i>0 THEN '.' ELSE '' END)+split(replace(ec,'-',''),'.')[i]) as ec_trunc
        WITH target, ec_trunc, sum(r.weight) as score ORDER BY score DESC
        WITH target, collect({{ec:ec_trunc, score:score}}) as cands, sum(score) as total
        RETURN target.entry as entry, cands, total
        """
        result = session.run(query, mw=min_weight)
        batch = []
        for r in result:
            ent = r["entry"]
            cands = r["cands"]
            tot = r["total"]
            if not cands or tot==0: continue
            
            best = cands[0]
            if (best["score"]/tot) >= conf_thresh:
                lbl = best["ec"]
                batch.append({"entry": ent, "ec": lbl})
                updates.append({"entry": ent, "ec_numbers": [lbl], "level": level})
        
        if batch:
            print(f"      -> {len(batch)} found.")
            session.run("UNWIND $b as row MATCH (n:Protein {entry:row.entry}) SET n.temp_known=true, n.temp_ec=row.ec", b=batch)
            
    session.run("MATCH (n:Protein) REMOVE n.temp_known, n.temp_ec")
    return updates

# --- CONTROLLEUR PROPAGATION (Appelé par le Front) ---
def run_prediction_for_frontend(min_weight_threshold: float = 0.0, strategy: str = "baseline"):
    updates = []
    print(f"🚀 Propagation Réelle | Stratégie : {strategy}")

    with driver.session(database=database_name) as session:
        
        # 1. SETUP LABELED/UNLABELED
        session.run("MATCH (n:Protein) REMOVE n.subset")
        session.run("MATCH (n:Protein) SET n.subset = CASE WHEN size(n.ec_numbers)>0 THEN 'labeled' ELSE 'unlabeled' END")

        # 2. CHOIX STRATEGIE
        if strategy == "baseline":
            query = """
            MATCH (target:Protein {subset: 'unlabeled'})
            MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'labeled'})
            WHERE r.weight > $mw
            UNWIND neighbor.ec_numbers AS ec
            WITH target, ec, sum(r.weight) AS score ORDER BY score DESC
            WITH target, collect({ec: ec, score: score}) AS preds
            RETURN target.entry AS entry, preds
            """
            res = session.run(query, mw=min_weight_threshold)
            for rec in res:
                preds = rec["preds"]
                if preds:
                    full = [p for p in preds if get_ec_level(p["ec"])==4]
                    if full: updates.append({"entry": rec["entry"], "ec_numbers": [full[0]["ec"]]})

        elif strategy == "consensus":
            query = """
            MATCH (target:Protein {subset: 'unlabeled'})
            MATCH (target)-[r:SIMILAR]-(neighbor:Protein {subset: 'labeled'})
            WHERE r.weight > $mw
            UNWIND neighbor.ec_hierarchy_labels AS ec
            WITH target, ec, sum(r.weight) AS score ORDER BY score DESC
            WITH target, collect({ec: ec, score: score}) AS preds
            RETURN target.entry AS entry, preds
            """
            res = session.run(query, mw=min_weight_threshold)
            for rec in res:
                preds = rec["preds"]
                if not preds: continue
                # Logic Consensus
                cands_lvl = defaultdict(list); tot_lvl = defaultdict(float)
                for p in preds:
                    l = get_ec_level(p["ec"])
                    cands_lvl[l].append(p); tot_lvl[l]+=p["score"]
                
                best_ec = None
                for l in [4,3,2,1]:
                    c = cands_lvl[l]
                    if c and (c[0]["score"]/tot_lvl[l] >= 0.6):
                        best_ec = c[0]["ec"]; break
                if best_ec: updates.append({"entry": rec["entry"], "ec_numbers": [best_ec]})

        elif strategy == "cascade":
            updates = compute_cascade_prediction_real(session, min_weight_threshold, 0.85)

        # 3. ECRITURE
        if not updates: return {"total_updated_neo4j": 0, "total_updated_mongo": 0, "examples": []}

        # Add hierarchy
        for u in updates:
            if "ec_hierarchy_labels" not in u:
                u["ec_hierarchy_labels"] = expand_ec(u["ec_numbers"])

        # Write Neo4j
        print(f"   💾 Neo4j Update ({len(updates)})...")
        batch_sz = 1000
        for i in range(0, len(updates), batch_sz):
            session.execute_write(lambda tx, b: tx.run("UNWIND $b AS row MATCH (p:Protein {entry: row.entry}) SET p.ec_numbers=row.ec_numbers, p.ec_hierarchy_labels=row.ec_hierarchy_labels", b=b), updates[i:i+batch_sz])

        # Write Mongo
        print("   💾 Mongo Update...")
        m_count = 0
        try:
            cli = MongoClient(MONGO_URI)
            db = cli[DB_NAME]; col = db[COLLECTION_NAME]
            ops = [UpdateOne({"_id": u["entry"], "$or": [{"annotations.ec_numbers": {"$exists": False}}, {"annotations.ec_numbers": None}, {"annotations.ec_numbers": []}]}, {"$set": {"annotations.ec_numbers": u["ec_numbers"]}}) for u in updates]
            if ops:
                for i in range(0, len(ops), 1000):
                    m_count += col.bulk_write(ops[i:i+1000]).modified_count
            cli.close()
        except Exception as e:
            print(f"Mongo Error: {e}")

        # Return Examples
        ex_out = [{"entry": u["entry"], "new_ec": u["ec_numbers"][0], "hierarchy": u.get("ec_hierarchy_labels", [])} for u in updates[:15]]
        
        return {
            "total_updated_neo4j": len(updates),
            "total_updated_mongo": m_count,
            "examples": ex_out
        }

if __name__ == "__main__":
    # Test rapide si lancé directement
    print("Test Validation...")
    res = run_validation_for_frontend(n_repeats=1, strategy="baseline")
    print(res["global_metrics"])