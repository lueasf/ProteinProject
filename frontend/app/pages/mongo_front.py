import streamlit as st
import sys
import os
from streamlit_searchbox import st_searchbox

# Ajouter le chemin du backend pour importer mongo_queries
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend', 'app'))
from mongo_queries import ProteinDatabase
# --- AJOUT: import du graphe Neo4j ---
from neo4j_query import build_subgraph

from delete_protein import delete_protein

# --- AJOUT: visualisation de graphe ---
try:
    from streamlit_agraph import agraph, Node, Edge, Config
    AGRAPH_AVAILABLE = True
except Exception:
    AGRAPH_AVAILABLE = False

@st.cache_data(show_spinner=False)
def cached_subgraph(entry_for_graph: str, k: int, m: int):
    # On passe les paramètres au backend
    return build_subgraph(entry_for_graph, k=k, m=m)

# Configuration de la page
st.set_page_config(
    page_title="Recherche de Protéines",
    page_icon="🧬",
    layout="wide"
)

# Initialisation de la connexion à la base de données (cache pour éviter reconnexions)
@st.cache_resource
def get_database():
    return ProteinDatabase()

# Fonction de recherche pour l'auto-complétion (appelée en temps réel)
def search_proteins(search_term: str):
    """Fonction appelée par st_searchbox pour chercher les protéines en temps réel"""
    if not search_term or len(search_term) < 2:
        return []
    
    try:
        db = get_database()
        suggestions = db.get_protein_suggestions(search_term, limit=10)
        
        # Retourner une liste de tuples (affichage, valeur)
        results = []
        for s in suggestions:
            entry_name = s.get('entry_name', '')
            protein_names = s.get('protein_names', '')
            
            # Extraire le premier nom pour l'affichage
            if isinstance(protein_names, list):
                first_name = protein_names[0] if protein_names else ''
            else:
                first_name = protein_names.split('(')[0].split(';')[0].strip()
            
            # Tronquer si trop long
            display = f"{entry_name} - {first_name[:45]}..." if len(first_name) > 45 else f"{entry_name} - {first_name}"
            results.append((display, entry_name))
        
        return results
    except Exception:
        return []

# Initialisation des session_state pour les champs dynamiques
if 'ec_groups' not in st.session_state:
    st.session_state.ec_groups = ['']  # Liste des groupes EC (1 champ par défaut)
if 'interpro_groups' not in st.session_state:
    st.session_state.interpro_groups = ['']  # Liste des groupes InterPro
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1

# États pour la suppression de protéines
if 'delete_message' not in st.session_state:
    st.session_state.delete_message = None  # {"type": "success"|"error", "text": "..."}
if 'confirm_delete' not in st.session_state:
    st.session_state.confirm_delete = None  # {"id": "...", "name": "..."} ou None

# Fonctions pour gérer les champs dynamiques
def add_ec_group():
    st.session_state.ec_groups.append('')

def remove_ec_group(index):
    if len(st.session_state.ec_groups) > 1:
        st.session_state.ec_groups.pop(index)

def add_interpro_group():
    st.session_state.interpro_groups.append('')

def remove_interpro_group(index):
    if len(st.session_state.interpro_groups) > 1:
        st.session_state.interpro_groups.pop(index)

def reset_all():
    st.session_state.ec_groups = ['']
    st.session_state.interpro_groups = ['']
    st.session_state.current_page = 1

# Titre principal
st.title("🧬 Recherche de Protéines")
st.markdown("---")

# Guide d'utilisation dans un expander
with st.expander("ℹ️ Guide d'utilisation des filtres"):
    st.markdown("""
    ### Comment utiliser les filtres EC et InterPro
    
    **Logique de recherche :**
    - Dans un même champ : les valeurs séparées par des virgules sont combinées avec **AND**
    - Entre différents champs (ajoutés avec ➕) : les groupes sont combinés avec **OR**
    
    **Exemple :**
    - Champ 1 : `1.14.14.19`
    - Champ 2 : `1.14.14.1, 4.2.1.152`
    - → Recherche : `1.14.14.19 OR (1.14.14.1 AND 4.2.1.152)`
    
    Cela trouve les protéines ayant soit EC 1.14.14.19, soit les deux EC 1.14.14.1 et 4.2.1.152.
    """)

# ===========================================
# BARRE DE RECHERCHE CENTRALE (auto-complétion)
# ===========================================
st.subheader("� Recherche rapide par nom de protéine")

# Searchbox avec auto-complétion en temps réel au centre de la page
selected_protein = st_searchbox(
    search_proteins,
    key="protein_searchbox",
    placeholder="🔍 Tapez pour rechercher une protéine (ex: Immunoglobulin, cytochrome...)",
    clear_on_submit=False,
    default=None,
)

st.markdown("---")

# ===========================================
# SIDEBAR - Filtres de recherche par caractéristiques
# ===========================================
st.sidebar.header("🔍 Filtres de Recherche")

# 1. Recherche par mot-clé (filtre classique)
keyword = st.sidebar.text_input(
    "Mot-clé (nom de protéine)", 
    placeholder="Ex: cytochrome, kinase...",
    help="Recherche dans le nom de la protéine et les noms associés"
)

# 2. Recherche par organisme
organism = st.sidebar.text_input(
    "Organisme",
    placeholder="Ex: Mus musculus, human...",
    help="Filtrer par organisme"
)

# 3. Recherche par sous-séquence
sequence = st.sidebar.text_input(
    "Sous-séquence",
    placeholder="Ex: MKTAYIAK, GVLFGVF...",
    help="Recherche de protéines contenant cette sous-séquence"
)

# 4. Numéros EC (Enzyme Commission) - Champs dynamiques
st.sidebar.subheader("📊 Annotations EC")
st.sidebar.caption("Virgule = AND | Nouveaux champs = OR")

# Afficher les champs EC existants
for i in range(len(st.session_state.ec_groups)):
    col1, col2 = st.sidebar.columns([5, 1])
    with col1:
        st.session_state.ec_groups[i] = st.text_input(
            f"Groupe EC {i+1}" if i > 0 else "Numéros EC",
            value=st.session_state.ec_groups[i],
            placeholder="Ex: 1.14.14.1, 4.2.1.152",
            key=f"ec_input_{i}",
            label_visibility="collapsed" if i > 0 else "visible"
        )
    with col2:
        if i > 0:  # Ne pas permettre de supprimer le premier champ
            if st.button("🗑️", key=f"remove_ec_{i}", help="Supprimer ce groupe"):
                remove_ec_group(i)
                st.rerun()

# Bouton pour ajouter un groupe EC
if st.sidebar.button("➕ Ajouter groupe EC (OR)", key="add_ec", use_container_width=True):
    add_ec_group()
    st.rerun()

# 5. InterPro - Champs dynamiques
st.sidebar.subheader("🏷️ Annotations InterPro")
st.sidebar.caption("Virgule = AND | Nouveaux champs = OR")

# Afficher les champs InterPro existants
for i in range(len(st.session_state.interpro_groups)):
    col1, col2 = st.sidebar.columns([5, 1])
    with col1:
        st.session_state.interpro_groups[i] = st.text_input(
            f"Groupe InterPro {i+1}" if i > 0 else "Identifiants InterPro",
            value=st.session_state.interpro_groups[i],
            placeholder="Ex: IPR000001, IPR000002",
            key=f"interpro_input_{i}",
            label_visibility="collapsed" if i > 0 else "visible"
        )
    with col2:
        if i > 0:
            if st.button("🗑️", key=f"remove_interpro_{i}", help="Supprimer ce groupe"):
                remove_interpro_group(i)
                st.rerun()

# Bouton pour ajouter un groupe InterPro
if st.sidebar.button("➕ Ajouter groupe InterPro (OR)", key="add_interpro", use_container_width=True):
    add_interpro_group()
    st.rerun()

# 6. Longueur de séquence
st.sidebar.subheader("📏 Longueur de Séquence")
col1, col2 = st.sidebar.columns(2)
with col1:
    length_min = st.number_input("Min", min_value=0, value=0, step=50)
with col2:
    length_max = st.number_input("Max", min_value=0, value=0, step=50, help="0 = pas de limite")

# 7. Pagination
st.sidebar.subheader("📄 Pagination")
page_size = st.sidebar.selectbox(
    "Résultats par page",
    options=[10, 20, 50, 100],
    index=1
)

# Bouton de recherche
search_button = st.sidebar.button("🔍 Rechercher", type="primary", use_container_width=True)

# Bouton reset
if st.sidebar.button("🔄 Réinitialiser", use_container_width=True):
    reset_all()
    st.rerun()

# Fonction pour construire l'expression avancée à partir des groupes
def build_advanced_expression(groups):
    """
    Transforme une liste de groupes en expression pour mongo_queries.
    Ex: ['1.14.14.19', '1.14.14.1, 4.2.1.152'] -> '(1.14.14.19) OR (1.14.14.1 AND 4.2.1.152)'
    """
    # Filtrer les groupes vides
    valid_groups = [g.strip() for g in groups if g.strip()]
    
    if not valid_groups:
        return None
    
    if len(valid_groups) == 1:
        # Un seul groupe : vérifier s'il y a des virgules (AND implicite)
        group = valid_groups[0]
        values = [v.strip() for v in group.split(',') if v.strip()]
        if len(values) == 1:
            return values[0]  # Valeur simple
        else:
            # Plusieurs valeurs = AND
            return f"({' AND '.join(values)})"
    
    # Plusieurs groupes : construire l'expression OR
    expressions = []
    for group in valid_groups:
        values = [v.strip() for v in group.split(',') if v.strip()]
        if len(values) == 1:
            expressions.append(f"({values[0]})")
        else:
            expressions.append(f"({' AND '.join(values)})")
    
    return ' OR '.join(expressions)

# Construction des filtres
def build_filters():
    filters = {}
    
    # Priorité à la barre de recherche centrale (selected_protein) si elle est utilisée
    # Sinon, utiliser le mot-clé de la sidebar
    if selected_protein:
        filters["keyword"] = selected_protein
    elif keyword:
        filters["keyword"] = keyword
    
    if organism:
        filters["organism"] = organism
    
    if sequence:
        filters["sequence"] = sequence
    
    # Construction de l'expression EC
    ec_expression = build_advanced_expression(st.session_state.ec_groups)
    if ec_expression:
        filters["ec"] = {
            "values": ec_expression,
            "mode": "AND"  # Le mode est géré par l'expression elle-même
        }
    
    # Construction de l'expression InterPro
    interpro_expression = build_advanced_expression(st.session_state.interpro_groups)
    if interpro_expression:
        filters["interpro"] = {
            "values": interpro_expression,
            "mode": "AND"
        }
    
    if length_min > 0 or length_max > 0:
        filters["length"] = {}
        if length_min > 0:
            filters["length"]["min"] = length_min
        if length_max > 0:
            filters["length"]["max"] = length_max
    
    return filters

# Affichage des résultats
def display_results(results_data):
    total = results_data["total_matches"]
    page = results_data["page"]
    per_page = results_data["per_page"]
    results = results_data["results"]
    
    # Statistiques
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📊 Total de résultats", total)
    with col2:
        st.metric("📄 Page actuelle", f"{page} / {max(1, (total + per_page - 1) // per_page)}")
    with col3:
        st.metric("🔢 Résultats affichés", len(results))
    
    st.markdown("---")
    
    # ======== MESSAGE DE SUPPRESSION ========
    if st.session_state.delete_message:
        msg = st.session_state.delete_message
        col_msg, col_close = st.columns([10, 1])
        with col_msg:
            if msg["type"] == "success":
                st.success(msg["text"])
            else:
                st.error(msg["text"])
        with col_close:
            if st.button("✖", key="close_delete_msg", help="Fermer"):
                st.session_state.delete_message = None
                st.rerun()
        st.markdown("---")
    
    # ======== MODAL DE CONFIRMATION ========
    if st.session_state.confirm_delete:
        protein_id = st.session_state.confirm_delete["id"]
        protein_name = st.session_state.confirm_delete["name"]
        
        st.warning(f"⚠️ **Confirmation de suppression**")
        st.markdown(f"Êtes-vous sûr de vouloir supprimer la protéine **`{protein_name}`** (ID: `{protein_id}`) ?")
        st.markdown("Cette action est **irréversible** et supprimera la protéine de MongoDB et Neo4j.")
        
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("✅ Oui, supprimer", key="confirm_delete_btn", type="primary"):
                # Effectuer la suppression
                delete_result = delete_protein(protein_id)
                if delete_result["mongodb"]["deleted"] or delete_result["neo4j"]["deleted"]:
                    st.session_state.delete_message = {
                        "type": "success",
                        "text": f"✅ Protéine `{protein_name}` supprimée avec succès."
                    }
                else:
                    st.session_state.delete_message = {
                        "type": "error",
                        "text": f"❌ Échec de la suppression de la protéine `{protein_name}`."
                    }
                st.session_state.confirm_delete = None
                st.rerun()
        with col_cancel:
            if st.button("❌ Annuler", key="cancel_delete_btn"):
                st.session_state.confirm_delete = None
                st.rerun()
        
        st.markdown("---")
    
    if not results:
        st.warning("Aucun résultat trouvé. Essayez de modifier vos critères de recherche.")
        return
    
    # Affichage sous forme de tableau
    for idx, protein in enumerate(results):
        # Identifiant stable par résultat
        entry_for_graph = protein.get('_id') or str(idx)
        expander_key = f"exp_open_{entry_for_graph}"
        graph_key = f"graph_open_{entry_for_graph}"

        # États par défaut
        if expander_key not in st.session_state:
            st.session_state[expander_key] = False
        if graph_key not in st.session_state:
            st.session_state[graph_key] = False

        label = f"🧬 **{protein.get('entry_name', 'N/A')}** - {protein.get('protein_names', 'N/A')[:80]}..."
        with st.expander(label, expanded=st.session_state[expander_key]):
            # Forcer l’expander à rester ouvert si le graphe est affiché
            if st.session_state[graph_key] and not st.session_state[expander_key]:
                st.session_state[expander_key] = True
                st.rerun()  # remplace st.experimental_rerun

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Informations générales**")
                st.write(f"**ID:** `{protein.get('_id', 'N/A')}`")
                st.write(f"**Entry Name:** {protein.get('entry_name', 'N/A')}")
                st.write(f"**Organisme:** {protein.get('organism', 'N/A')}")
                st.write(f"**Longueur:** {protein.get('sequence_length', 'N/A')} aa")

            with col2:
                st.markdown("**Annotations**")
                annotations = protein.get('annotations', {})
                ec_numbers = annotations.get('ec_numbers', [])
                if ec_numbers:
                    st.write(f"**EC Numbers:** {', '.join(ec_numbers) if isinstance(ec_numbers, list) else ec_numbers}")
                else:
                    st.write("**EC Numbers:** Aucun")
                interpro_ids = annotations.get('interpro', [])
                if interpro_ids:
                    if isinstance(interpro_ids, list):
                        st.write(f"**InterPro:** {', '.join(interpro_ids[:5])}{'...' if len(interpro_ids) > 5 else ''}")
                    else:
                        st.write(f"**InterPro:** {interpro_ids}")
                else:
                    st.write("**InterPro:** Aucun")
                
                # Bouton pour demander confirmation de suppression
                if st.button("Supprimer cette protéine", key=f"delete_btn_{entry_for_graph}", type="primary"):
                    st.session_state.confirm_delete = {
                        "id": protein.get('_id'),
                        "name": protein.get('entry_name', 'N/A')
                    }
                    st.rerun()

            st.markdown("**Nom complet de la protéine:**")
            st.info(protein.get('protein_names', 'N/A'))

            # --- Graphe Neo4j (lazy, état persistant) ---
            st.markdown("**Graphe de similarité (Neo4j)**")
            if not AGRAPH_AVAILABLE:
                st.warning("La visualisation nécessite 'streamlit-agraph'. Installez-le avec: pip install streamlit-agraph")
            else:
                # Bouton qui ne fait que basculer l’état puis rerun
                if not st.session_state[graph_key]:
                    if st.button("Afficher le graphe", key=f"btn_show_graph_{entry_for_graph}"):

                        st.session_state[graph_key] = True
                        st.session_state[expander_key] = True
                        st.rerun()
                else:
                    if st.button("Masquer le graphe", key=f"btn_hide_graph_{entry_for_graph}"):

                        st.session_state[graph_key] = False
                        # On laisse l’expander ouvert par choix UX; sinon mettre False
                        st.rerun()

                if st.session_state[graph_key]:
                    st.markdown("---")
                    
                    # --- PARAMÈTRES DU GRAPHE ---
                    # On permet à l'utilisateur de régler la densité
                    c_param1, c_param2, c_legend = st.columns([1, 1, 2])
                    with c_param1:
                        k_val = st.slider(f"Voisins directs (k) - {entry_for_graph}", 1, 20, 5, key=f"k_{entry_for_graph}")
                    with c_param2:
                        m_val = st.slider(f"Voisins niv.2 (m) - {entry_for_graph}", 0, 10, 2, key=f"m_{entry_for_graph}")
                    with c_legend:
                        st.info(
                            "🔴 **Rouge** : Protéine Cible\n\n"
                            "🔵 **Bleu** : Voisins directs (Niveau 1)\n\n"
                            "🟢 **Vert** : Voisins de voisins (Niveau 2)"
                        )

                    with st.spinner("Construction du graphe..."):
                        try:
                            # Appel avec les paramètres dynamiques
                            subgraph = cached_subgraph(entry_for_graph, k=k_val, m=m_val)
                        except Exception as e:
                            subgraph = None
                            st.error(f"Erreur Neo4j: {e}")

                    if not subgraph:
                        st.warning("Cette protéine n'a pas été trouvée dans la base de données Neo4j.")
                    
                    else:
                        nodes_list = subgraph.get("nodes", [])
                        edges_list = subgraph.get("edges", [])
                        
                        # Détection : est-ce un nœud isolé ?
                        is_isolated = len(nodes_list) == 1
                        
                        # Affichage du message si isolé
                        if is_isolated:
                            st.info("⚠️ **Nœud isolé** : Cette protéine ne possède pas de voisins similaires (arêtes) avec les paramètres actuels.")
                        nodes = []
                        for n in nodes_list:
                            # --- NOUVELLE LOGIQUE DE COULEURS ---
                            # On se base strictement sur le groupe renvoyé par le backend
                            similarity = n.get("similarity", 0)
                            group = n.get("group", "neighbor")

                            # Formatage du score en pourcentage (ex: 0.954 -> 95.4%)
                            if group == "center":
                                score_display = "REF (100%)"
                            elif similarity:
                                score_display = f"{similarity:.1%}" # Formatage Python auto
                            else:
                                score_display = "N/A"
                            
                            if group == "center":
                                color = "#ff4b4b"  # Rouge (Streamlit primary)
                                size = 35
                                label_node = n.get("entry")  # Label visible
                            elif group == "level1":
                                color = "#1c83e1"  # Bleu vif
                                size = 25
                                label_node = n.get("entry")
                            elif group == "level2":
                                color = "#09ab3b"  # Vert
                                size = 15
                                # Pour le niveau 2, on peut cacher le label pour alléger si on veut
                                label_node = n.get("entry") 
                            else:
                                color = "#adb5bd" # Gris par défaut
                                size = 10
                                label_node = ""

                            # Construction du tooltip
                            entry = n.get("entry", "")
                            entry_name = n.get("entry_name", "")
                            organism = n.get("organism", "")
                            protein_names = n.get("protein_names", [])
                            ec_numbers = n.get("ec_numbers", [])
                            interpro_list = n.get("interpro_list", [])
                            
                            # Gestion propre des listes pour l'affichage
                            if isinstance(protein_names, list):
                                p_names_str = "; ".join(protein_names[:2]) # On n'en montre que 2
                            else:
                                p_names_str = str(protein_names)
                                
                            title = (
                                f"[{group.upper()}] - Sim: {score_display}\n" 
                                f"-----------------------------\n"
                                f"ID: {entry}\n"
                                f"Name: {entry_name}\n"
                                f"Org: {organism}\n"
                                f"Desc: {p_names_str[:100]}..."
                                f"\nEC: {', '.join(ec_numbers) if isinstance(ec_numbers, list) else ec_numbers}"
                                f"\nInterPro: {', '.join(interpro_list) if isinstance(interpro_list, list) else interpro_list}"
                            )

                            nodes.append(
                                Node(
                                    id=entry,
                                    label=label_node,
                                    size=size,
                                    title=title,
                                    color=color,
                                    shape="dot",
                                    borderWidth=2,
                                    borderWidthSelected=4,
                                )
                            )

                        edges = []
                        for e in edges_list:
                            # Récupération du poids (de 0 à 1)
                            weight = e.get("weight", 0)
                            
                            # Sécurité : on s'assure que le poids est entre 0 et 1
                            weight = max(0, min(1, weight))
                            
                            # --- CALCUL DE LA DISTANCE PHYSIQUE ---
                            # Distance basée sur la dissimilarité (1 - weight)
                            # weight = 0.99 -> length = 150 + (0.01 * 400) = 154px
                            # weight = 0.50 -> length = 150 + (0.50 * 400) = 350px
                            # weight = 0.10 -> length = 150 + (0.90 * 400) = 510px
                            edge_length = 150 + (1 - weight) * 400
                            
                            # --- CALCUL DE L'ÉPAISSEUR VISUELLE ---
                            # Arêtes fines : de 0.3px à 2px
                            edge_width = 0.3 + (weight * 1.7)
                            
                            edge_color = "#d3d3d3"
                            
                            edges.append(Edge(
                                source=e["source"], 
                                target=e["target"],
                                color=edge_color,
                                width=edge_width,
                                length=edge_length
                            ))
                        
                        config = Config(
                            width=1000,
                            height=600,
                            directed=False,
                            physics=True,
                            hierarchical=False,
                            physicsOptions={
                                "barnesHut": {
                                    "gravitationalConstant": -3000,  # Augmenté pour plus de répulsion
                                    "centralGravity": 0.2,           # Réduit pour moins attirer au centre
                                    "springConstant": 0.08,          # Augmenté pour mieux respecter edge_length
                                    "springLength": 200,             # Distance de repos des ressorts
                                    "damping": 0.15,                 # Augmenté pour stabiliser plus vite
                                    "avoidOverlap": 0.8              # Augmenté pour éviter les chevauchements
                                },
                                "stabilization": {
                                    "enabled": True,
                                    "iterations": 200                # Plus d'itérations pour converger
                                }
                            }
                        )
                        
                        left, center_col, right = st.columns([1, 10, 1])
                        with center_col:
                            agraph(nodes=nodes, edges=edges, config=config) # Pas de key=agraph_key ici parfois ça bug avec agraph, test sans d'abord

    # Pagination
    st.markdown("---")
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
    
    with col1:
        if st.button("⏮️ Début", disabled=(page == 1)):
            st.session_state.current_page = 1
            st.rerun()
    
    with col2:
        if st.button("◀️ Précédent", disabled=(page == 1)):
            st.session_state.current_page = page - 1
            st.rerun()
    
    with col3:
        st.markdown(f"<p style='text-align: center;'>Page {page} sur {total_pages}</p>", unsafe_allow_html=True)
    
    with col4:
        if st.button("Suivant ▶️", disabled=(page >= total_pages)):
            st.session_state.current_page = page + 1
            st.rerun()
    
    with col5:
        if st.button("Fin ⏭️", disabled=(page >= total_pages)):
            st.session_state.current_page = total_pages
            st.rerun()

# Logique principale
try:
    db = get_database()
    
    # Afficher un message de connexion réussie
    st.sidebar.success("✅ Connecté à MongoDB")
    
    # Exécuter la recherche
    filters = build_filters()
    
    # Afficher les filtres actifs
    if filters:
        st.subheader("🎯 Filtres actifs")
        filter_tags = []
        if filters.get("keyword"):
            filter_tags.append(f"🔤 Mot-clé: `{filters['keyword']}`")
        if filters.get("organism"):
            filter_tags.append(f"🦠 Organisme: `{filters['organism']}`")
        if filters.get("sequence"):
            filter_tags.append(f"🧬 Séquence: `{filters['sequence']}`")
        if filters.get("ec"):
            ec_expr = filters['ec']['values']
            filter_tags.append(f"📊 EC: `{ec_expr}`")
        if filters.get("interpro"):
            ipr_expr = filters['interpro']['values']
            filter_tags.append(f"🏷️ InterPro: `{ipr_expr}`")
        if filters.get("length"):
            length_str = f"Min: {filters['length'].get('min', '-')}, Max: {filters['length'].get('max', '-')}"
            filter_tags.append(f"📏 Longueur: `{length_str}`")
        
        st.markdown(" | ".join(filter_tags))
        st.markdown("---")
    
    # Effectuer la recherche
    with st.spinner("🔍 Recherche en cours..."):
        results = db.advanced_search(
            filters=filters,
            page=st.session_state.current_page,
            page_size=page_size
        )
    
    # Afficher les résultats
    display_results(results)

except Exception as e:
    st.error(f"❌ Erreur de connexion à la base de données: {e}")
    st.info("Vérifiez que MongoDB est en cours d'exécution et que les variables d'environnement sont configurées.")


import plotly.express as px
from stats import compute_protein_stats  # nouveau
@st.cache_data(show_spinner=False)
def get_global_protein_stats():
    """
    Wrap de compute_protein_stats() avec cache Streamlit,
    pour éviter de relire les gros CSV à chaque interaction.
    """
    return compute_protein_stats()


# ==============================
# Statistiques globales (CSV)
# ==============================
with st.expander("📈 Statistiques globales (nodes.csv / edges.csv)", expanded=False):
    try:
        stats = get_global_protein_stats()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total de protéines", stats["total_proteins"])
        with col2:
            st.metric("Labellisées (EC)", stats["labelled_proteins"])
            st.metric(
                "Ratio labellées (%)",
                f"{stats['labelled_ratio']:.1f}"
            )
        with col3:
            st.metric("Isolées", stats["isolated_proteins"])
            st.metric(
                "Ratio isolées (%)",
                f"{stats['isolated_ratio']:.1f}"
            )

        st.markdown("### Répartitions")

        # ========= Camembert 1 : Labellisées vs non labellisées =========
        labels_1 = ["Labellisées", "Non labellisées"]
        values_1 = [
            stats["labelled_proteins"],
            stats["unlabelled_proteins"],
        ]

        fig1 = px.pie(
            names=labels_1,
            values=values_1,
            hole=0.3,
            title="Labellisées vs non labellisées",
        )
        fig1.update_traces(
            textposition="inside",
            textinfo="percent+label"
        )
        fig1.update_layout(
            margin=dict(t=40, b=10, l=10, r=10),
            showlegend=False,
        )

        non_isolated = stats["total_proteins"] - stats["isolated_proteins"]
        labels_2 = ["Isolées", "Non isolées"]
        values_2 = [
            stats["isolated_proteins"],
            non_isolated,
        ]

        fig2 = px.pie(
            names=labels_2,
            values=values_2,
            hole=0.3,
            title="Isolées vs non isolées",
        )
        fig2.update_traces(
            textposition="inside",
            textinfo="percent+label"
        )
        fig2.update_layout(
            margin=dict(t=40, b=10, l=10, r=10),
            showlegend=False,
        )

        # Affichage côte à côte
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(fig1, use_container_width=True)
        with c2:
            st.plotly_chart(fig2, use_container_width=True)

    except Exception as e:
        st.error(f"Erreur lors du calcul des statistiques globales : {e}")


# Footer
st.markdown("---")
st.markdown(
    "<p style='text-align: center; color: gray;'>🧬 Protein Database Explorer | Powered by Streamlit & MongoDB</p>",
    unsafe_allow_html=True
)
