import pandas as pd
import numpy as np
import random
import math

from collections import defaultdict

def preprocess_domains(df):
    """
    Transforme la colonne InterPro en ensembles de domaines par protéine.
    """
    domains_per_node = []
    for v in df["InterPro"]:
        if isinstance(v, str) and v.strip():
            s = {tok for tok in v.split(";") if tok}
        else:
            s = set()
        domains_per_node.append(s)
    return domains_per_node


def build_graph_from_interpro(df, max_group_size=500, min_jaccard=0.1, k_nn=None):
    """
    Construit un graphe pondéré entre protéines selon la similarité Jaccard-IDF de leurs domaines InterPro.

    - On calcule un poids idf[d] = log(N / df(d)) pour chaque domaine InterPro.
    - Similarité entre deux protéines i, j :
        J_IDF(i, j) = sum_{d in A∩B} idf[d] / sum_{d in AuB} idf[d]
      où A = domaines(i), B = domaines(j)

    Paramètres :
    - max_group_size : on ignore les domaines présents dans trop de protéines (peu informatifs + coût).
    - min_jaccard   : seuil minimum sur J_IDF pour garder une arête.
    - k_nn          : si non None, ne garde que les k voisins les plus proches par nœud.
    """
    domains_per_node = preprocess_domains(df)
    n = len(df)

    domain_df = defaultdict(int)
    for doms in domains_per_node:
        for d in doms:
            domain_df[d] += 1

    idf = {}
    N = n
    for d, freq in domain_df.items():
        if freq == 0:
            continue
        idf[d] = math.log(N / freq)

    domain_to_nodes = defaultdict(list)
    for i, doms in enumerate(domains_per_node):
        for d in doms:
            domain_to_nodes[d].append(i)

    adj = [dict() for _ in range(n)]
    pairs_done = defaultdict(set)  # pour ne pas recalculer plusieurs fois le même couple

    for d, nodes in domain_to_nodes.items():
        m = len(nodes)
        if m < 2 or m > max_group_size:
            continue

        for idx_i in range(m):
            u = nodes[idx_i]
            doms_u = domains_per_node[u]
            if not doms_u:
                continue

            for idx_j in range(idx_i + 1, m):
                v = nodes[idx_j]
                if u > v:
                    u, v = v, u
                    doms_u, doms_v = domains_per_node[u], domains_per_node[v]
                else:
                    doms_v = domains_per_node[v]

                if v in pairs_done[u]:
                    continue
                pairs_done[u].add(v)

                inter = doms_u & doms_v
                if not inter:
                    continue
                union = doms_u | doms_v

                inter_w = sum(idf.get(x, 0.0) for x in inter)
                union_w = sum(idf.get(x, 0.0) for x in union)
                if union_w == 0.0:
                    continue

                w = inter_w / union_w
                if w < min_jaccard:
                    continue

                adj[u][v] = w
                adj[v][u] = w

    if k_nn is not None:
        new_adj = [dict() for _ in range(n)]
        for i in range(n):
            if not adj[i]:
                continue
            sorted_neighbors = sorted(adj[i].items(), key=lambda x: x[1], reverse=True)
            for j, w in sorted_neighbors[:k_nn]:
                new_adj[i][j] = w

        sym_adj = [dict() for _ in range(n)]
        for i in range(n):
            for j, w in new_adj[i].items():
                sym_adj[i][j] = max(sym_adj[i].get(j, 0.0), w)
                sym_adj[j][i] = max(sym_adj[j].get(i, 0.0), w)
        adj = sym_adj

    return adj, domains_per_node

def prepare_labels(df):
    """
    Crée la matrice de labels one-hot Y pour toutes les protéines ayant un numéro EC connu.
    """
    ec_series = df["EC number"]
    labeled_mask = ec_series.notna()
    labeled_indices = np.where(labeled_mask)[0]

    unique_ec = sorted(ec_series.dropna().unique())
    ec_to_idx = {ec: i for i, ec in enumerate(unique_ec)}
    num_classes = len(unique_ec)
    n = len(df)

    Y = np.zeros((n, num_classes), dtype=float)
    for i in labeled_indices:
        ec = ec_series.iloc[i]
        Y[i, ec_to_idx[ec]] = 1.0

    return Y, labeled_indices, ec_to_idx, unique_ec


def label_propagation(adj, Y, alpha=0.9, max_iter=50, tol=1e-6):
    """
     Propage les labels EC sur le graphe via l'itération F^{t+1} = alpha * S F^t + (1 - alpha) * Y avec normalisation symétrique.
    """
    n, C = Y.shape
    F = Y.copy()

    degrees = np.array([sum(neighbors.values()) for neighbors in adj], dtype=float)
    degrees[degrees == 0.0] = 1.0  # évite division par 0

    for it in range(max_iter):
        F_new = np.zeros_like(F)

        for i, neighbors in enumerate(adj):
            if not neighbors:
                continue
            sqrt_deg_i = np.sqrt(degrees[i])
            for j, w in neighbors.items():
                sqrt_deg_j = np.sqrt(degrees[j])
                w_norm = w / (sqrt_deg_i * sqrt_deg_j)
                F_new[i] += w_norm * F[j]

        F_new = alpha * F_new + (1.0 - alpha) * Y

        diff = np.abs(F_new - F).max()
        F = F_new
        if diff < tol:
            break

    row_norms = F.sum(axis=1, keepdims=True)
    row_norms[row_norms == 0.0] = 1.0
    F = F / row_norms
    return F

def holdout_evaluation(df, adj, test_fraction=0.3, alpha=0.9, max_iter=50, seed=0):
    """
    Évalue la propagation en masquant une partie des EC connus et en comparant prédiction vs vérité.
    """
    rng = np.random.default_rng(seed)

    Y_full, labeled_indices, ec_to_idx, unique_ec = prepare_labels(df)
    n, C = Y_full.shape

    labeled_indices = np.array(labeled_indices)
    rng.shuffle(labeled_indices)

    split = int((1.0 - test_fraction) * len(labeled_indices))
    train_idx = labeled_indices[:split]
    test_idx = labeled_indices[split:]

    Y = np.zeros_like(Y_full)
    for i in train_idx:
        Y[i] = Y_full[i]

    F = label_propagation(adj, Y, alpha=alpha, max_iter=max_iter)

    # vraie classe de chaque nœud (pour ceux qui étaient labellisés à l'origine)
    true_labels = Y_full.argmax(axis=1)

    correct = 0
    total = 0
    for i in test_idx:
        # on ne considère que les nœuds qui ont récupéré une distribution non nulle
        if F[i].sum() == 0:
            continue
        pred = F[i].argmax()
        if pred == true_labels[i]:
            correct += 1
        total += 1

    acc = correct / total if total > 0 else float("nan")
    return acc, train_idx, test_idx, F, ec_to_idx, unique_ec


def show_example_predictions(df, F, test_idx, ec_to_idx, unique_ec, k=10):
    """
    Affiche quelques exemples : Entry, vrai EC, EC prédit, proba max.
    """
    idx_to_ec = {v: k for k, v in ec_to_idx.items()}

    print("\nExemples de prédictions sur le set de test :")
    print("Entry\tTrue EC\tPred EC\tProb")
    shown = 0
    for i in test_idx:
        if shown >= k:
            break
        row = F[i]
        if row.sum() == 0:
            continue
        pred_idx = row.argmax()
        pred_ec = idx_to_ec[pred_idx]
        # vrai EC
        true_ec = df["EC number"].iloc[i]
        prob = row[pred_idx]
        entry = df["Entry"].iloc[i]
        print(f"{entry}\t{true_ec}\t{pred_ec}\t{prob:.3f}")
        shown += 1

def top_k_accuracy(F, Y_full, test_idx, k=3):
    """
    Calcule la fraction de protéines de test dont le vrai EC apparaît dans les k labels les plus probables.
    """
    true_labels = Y_full.argmax(axis=1)
    correct = 0
    total = 0

    for i in test_idx:
        if F[i].sum() == 0:
            continue
        top_k = np.argsort(F[i])[::-1][:k]
        if true_labels[i] in top_k:
            correct += 1
        total += 1

    return correct / total if total > 0 else float("nan")

def propagate_and_fill_missing_ec(df, adj, alpha=0.9, max_iter=50):
    """
    Utilise tous les EC connus comme labels de départ, propage sur le graphe,
    puis remplit les EC manquants avec les prédictions (et ajoute proba).
    Les lignes qui avaient déjà un EC gardent leur valeur dans EC number.

    Toutes les lignes sans EC reçoivent :

        EC_pred : l'EC prédit par LP,
        EC_pred_conf : la probabilité associée,
        EC_filled : EC réel si connu, sinon EC préd
    """
    Y_full, labeled_indices, ec_to_idx, unique_ec = prepare_labels(df)

    F = label_propagation(adj, Y_full, alpha=alpha, max_iter=max_iter)

    idx_to_ec = {v: k for k, v in ec_to_idx.items()}

    n = len(df)
    ec_pred = []
    ec_pred_conf = []

    for i in range(n):
        row = F[i]
        if row.sum() == 0:
            ec_pred.append(None)
            ec_pred_conf.append(0.0)
            continue

        j = row.argmax()
        ec_pred.append(idx_to_ec[j])
        ec_pred_conf.append(row[j])

    df = df.copy()
    df["EC_pred"] = ec_pred
    df["EC_pred_conf"] = ec_pred_conf

    df["EC_filled"] = df["EC number"].where(df["EC number"].notna(), df["EC_pred"])

    return df



## main
if __name__ == "__main__":
    df = pd.read_csv("../../f.tsv", sep="\t")

    print("Nombre total de protéines :", len(df))
    print("Nombre de protéines avec EC connu :", df["EC number"].notna().sum())

    # construction du graphe
    print("Construction du graphe ...")
    adj, domains_per_node = build_graph_from_interpro(df, max_group_size=300, min_jaccard=0.1, k_nn=20,)
    nb_edges = sum(len(ne) for ne in adj) // 2
    print("Nombre de nœuds :", len(adj))
    print("Nombre d'arêtes (approx) :", nb_edges)

    # expérience de label propagation
    print("\nLabel propagation :")
    acc, train_idx, test_idx, F, ec_to_idx, unique_ec = holdout_evaluation(
        df,
        adj,
        test_fraction=0.3,   # 30% des EC connus cachés pour le test
        alpha=0.9,
        max_iter=50,
        seed=42,
    )
    Y_full, _, _, _ = prepare_labels(df)
    top3 = top_k_accuracy(F, Y_full, test_idx, k=3)
    print(f"Top-3 accuracy sur le set de test : {top3:.3f}")


    print(f"\nTaille train : {len(train_idx)}")
    print(f"Taille test  : {len(test_idx)}")
    print(f"Accuracy sur le set de test : {acc:.3f}")

    # quelques exemples de prédictions
    show_example_predictions(df, F, test_idx, ec_to_idx, unique_ec, k=10)
    print("\n")

    print("\nPropagation finale sur tout le graphe et remplissage des EC manquants")
    df_filled = propagate_and_fill_missing_ec(df, adj, alpha=0.9, max_iter=50)

    output_path = "f_with_EC_filled.tsv"
    df_filled.to_csv(output_path, sep="\t", index=False)
    print(f"Fichier sauvegardé avec EC remplis : {output_path}")




