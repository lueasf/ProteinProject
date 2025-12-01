# graph_builder.py

import pandas as pd
from collections import defaultdict

def build_protein_graph(tsv_file, nodes_file="nodes.csv", edges_file="edges.csv"):
    df = pd.read_csv(tsv_file, sep="\t", dtype=str)
    df = df.fillna("")
    df['InterPro_list'] = df['InterPro'].apply(lambda x: [d for d in x.split(";") if d] if x else [])
    df.drop(columns=['InterPro'], inplace=True)
    df_with_domains = df[df['InterPro_list'].map(len) > 0].copy()

    domain_to_proteins = defaultdict(set)
    for idx, row in df_with_domains.iterrows():
        entry = row['Entry']
        for domain in row['InterPro_list']:
            if domain:
                domain_to_proteins[domain].add(entry)

    edges = dict()
    for proteins in domain_to_proteins.values():
        proteins = list(proteins)
        for i in range(len(proteins)):
            for j in range(i+1, len(proteins)):
                p1, p2 = proteins[i], proteins[j]
                key = tuple(sorted([p1, p2]))
                edges.setdefault(key, 0)
                edges[key] += 1

    interpro_counts = {row['Entry']: len(row['InterPro_list']) for _, row in df_with_domains.iterrows()}

    final_edges = []
    for (p1, p2), shared_count in edges.items():
        union_count = interpro_counts[p1] + interpro_counts[p2] - shared_count
        weight = shared_count / union_count
        final_edges.append((p1, p2, weight))

    edges_df = pd.DataFrame(final_edges, columns=["Source", "Target", "Weight"])
    edges_df.to_csv(edges_file, index=False)
    print(f"{len(edges_df)} arêtes exportées dans {edges_file}")

    df['EC_numbers'] = df['EC number'].apply(lambda x: x.split(";") if x else [])
    df.to_csv(nodes_file, index=False)
    print(f"{len(df)} nœuds exportés dans {nodes_file}")

if __name__ == "__main__":
    build_protein_graph("data/raw/uniprot.tsv")
