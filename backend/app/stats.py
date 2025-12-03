import os
from typing import Dict, Optional
import pandas as pd


def _find_data_dir() -> str:

    here = os.path.dirname(os.path.abspath(__file__))

    backend_dir = os.path.abspath(os.path.join(here, ".."))

    project_root = os.path.abspath(os.path.join(backend_dir, ".."))

    candidate_backend = os.path.join(backend_dir, "data", "processed")
    candidate_root = os.path.join(project_root, "data", "processed")

    if os.path.isdir(candidate_backend):
        return candidate_backend
    if os.path.isdir(candidate_root):
        return candidate_root

    raise FileNotFoundError(
        "Impossible de trouver le dossier data/processed.\n"
        f"Chemins testés :\n  {candidate_backend}\n  {candidate_root}"
    )


def _load_nodes_edges(
    nodes_csv_path: Optional[str] = None,
    edges_csv_path: Optional[str] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Charge nodes.csv et edges.csv dans des DataFrame pandas.
    Si les chemins ne sont pas fournis, on les déduit du projet.
    """
    data_dir = _find_data_dir()

    if nodes_csv_path is None:
        nodes_csv_path = os.path.join(data_dir, "nodes.csv")
    if edges_csv_path is None:
        edges_csv_path = os.path.join(data_dir, "edges.csv")

    if not os.path.isfile(nodes_csv_path):
        raise FileNotFoundError(f"nodes.csv introuvable : {nodes_csv_path}")
    if not os.path.isfile(edges_csv_path):
        raise FileNotFoundError(f"edges.csv introuvable : {edges_csv_path}")

    nodes = pd.read_csv(nodes_csv_path)
    edges = pd.read_csv(edges_csv_path)

    return nodes, edges


def compute_protein_stats(
    nodes_csv_path: Optional[str] = None,
    edges_csv_path: Optional[str] = None,
) -> Dict[str, float]:
    """
    Calcule des statistiques globales à partir de nodes.csv et edges.csv.

    Renvoie un dict avec :
      - total_proteins
      - labelled_proteins    (au moins une annotation EC_numbers)
      - unlabelled_proteins
      - isolated_proteins    (aucun voisin dans edges)
      - labelled_ratio       (labelled / total)
      - isolated_ratio       (isolated / total)
    """
    nodes, edges = _load_nodes_edges(nodes_csv_path, edges_csv_path)

    if "Entry" not in nodes.columns:
        raise KeyError("La colonne 'Entry' est manquante dans nodes.csv")
    if "EC_numbers" not in nodes.columns:
        raise KeyError("La colonne 'EC_numbers' est manquante dans nodes.csv")
    for col in ["Source", "Target"]:
        if col not in edges.columns:
            raise KeyError(f"La colonne '{col}' est manquante dans edges.csv")

    ec_col = nodes["EC_numbers"].astype(str).str.strip()

    unlabel_values = {"", "[]", "nan", "None"}
    labelled_mask = ~ec_col.isin(unlabel_values)

    total_proteins = int(len(nodes))
    labelled_proteins = int(labelled_mask.sum())
    unlabelled_proteins = int(total_proteins - labelled_proteins)

    if len(edges) == 0:
        isolated_proteins = total_proteins
    else:
        connected_entries = pd.unique(
            pd.concat([edges["Source"], edges["Target"]], ignore_index=True)
        )
        connected_entries = pd.Series(connected_entries).dropna().astype(str)

        isolated_mask = ~nodes["Entry"].astype(str).isin(connected_entries)
        isolated_proteins = int(isolated_mask.sum())

    labelled_ratio = (labelled_proteins / total_proteins * 100.0) if total_proteins else 0.0
    isolated_ratio = (isolated_proteins / total_proteins * 100.0) if total_proteins else 0.0

    return {
        "total_proteins": total_proteins,
        "labelled_proteins": labelled_proteins,
        "unlabelled_proteins": unlabelled_proteins,
        "isolated_proteins": isolated_proteins,
        "labelled_ratio": labelled_ratio,
        "isolated_ratio": isolated_ratio,
    }


if __name__ == "__main__":
    stats = compute_protein_stats()
    print("=== Protein statistics ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
