import socket
import time
import threading 
import json
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np

IP = "127.0.0.1"

# This is where the Listener stores everything it hears
routing_data = {}
last_seen = {}
neighbors_map = {} 
last_known_state = "" 

G = nx.DiGraph()

def update_graph_object():
    """
    This function synchronizes the global 'G' graph object 
    with the latest data received by the listener.
    """
    global last_known_state
    current_time = time.time()  
    dead_nodes = []
    
    for node, l_time in last_seen.items():
        if current_time - l_time > 10:
            dead_nodes.append(node)
            
    for dead_node in dead_nodes:
        print(f"[!] Node {dead_node} is dead. Removing from map.")
        del last_seen[dead_node]
        if dead_node in neighbors_map:
            del neighbors_map[dead_node]
        if dead_node in routing_data:
            del routing_data[dead_node]
            
    current_state = json.dumps(neighbors_map, sort_keys=True)    
    if current_state == last_known_state:
        return False 
        
    last_known_state = current_state
    G.clear()
    
    for node, neighbors in neighbors_map.items():
        G.add_node(node)
        for neighbor_str, weight in neighbors.items():
            neighbor = int(neighbor_str)
            G.add_edge(node, neighbor, weight=weight)
            
    return True

def update_graph(_): 
    global node_positions
    changed = update_graph_object()
    
    if not changed and len(G.nodes) > 0:
        return
    
    plt.clf()
    if not G.nodes:
        return

    # 1. Force a large figure size to handle the split view
    fig = plt.gcf()
    fig.set_size_inches(12, 6) # Wide format for side-by-side

    # 2. Setup the layout manually
    # rect=[left, bottom, right, top]
    # We leave a gap between 0.45 and 0.55
    ax_graph = fig.add_axes([0.05, 0.1, 0.4, 0.8]) # Left side
    ax_data = fig.add_axes([0.55, 0.1, 0.4, 0.8])  # Right side

    node_positions = nx.circular_layout(G)

    # --- TOPOLOGY MAP (Left) ---
    plt.sca(ax_graph)
    ax_graph.margins(0.2)

    processed_edges = set()
    bidirectional_list = []
    unidirectional_list = []

    # UPDATED LOGIC: Filter out poisoned control links
    for u, v, data in G.edges(data=True):
        weight = data.get('weight', 1)
        
        # Ignore drawing the invisible "Control Plane" routes entirely
        if weight >= 99999:
            continue

        if (v, u) in processed_edges: 
            continue 

        # Check if a return path exists AND it isn't a poisoned control route
        has_real_return = G.has_edge(v, u) and G.edges[v, u].get('weight', 1) < 99999

        if has_real_return:
            bidirectional_list.append((u, v))
            processed_edges.update([(u, v), (v, u)])
        else:
            unidirectional_list.append((u, v))
            processed_edges.add((u, v))

    # Single line with double-headed arrows for bidirectional
    nx.draw_networkx_edges(G, node_positions, edgelist=bidirectional_list,
                           arrowstyle='<->', arrowsize=20, 
                           edge_color='blue', width=2, ax=ax_graph)

    nx.draw_networkx_edges(G, node_positions, edgelist=unidirectional_list,
                           arrowstyle='->', arrowsize=20, 
                           edge_color='black', width=1.5, ax=ax_graph)

    nx.draw_networkx_nodes(G, node_positions, node_size=800, node_color='skyblue', ax=ax_graph)
    nx.draw_networkx_labels(G, node_positions, font_weight='bold', ax=ax_graph)
    ax_graph.set_title("Physical Topology", pad=20)
    ax_graph.axis('off')

    # --- STATUS TABLE (Right) ---
    plt.sca(ax_data)
    ax_data.clear() # Added this to prevent text ghosting over time
    ax_data.axis('off')
    
    edge_labels = nx.get_edge_attributes(G, 'weight')
    table_text = "PORT TELEMETRY DATA\n" + "="*22 + "\n\n"
    
    for (u, v), w in sorted(edge_labels.items()):
        # UPDATED LOGIC: Hide the poisoned links from the human dashboard
        if w >= 99999:
            continue
            
        table_text += f" {u} ──► {v} | Cost: {w}\n"
        table_text += "─"*25 + "\n"

    # Using 'axes fraction' ensures the text stays inside its half of the screen
    plt.text(0, 1.0, table_text, transform=ax_data.transAxes, 
             fontsize=10, family='monospace', verticalalignment='top',
             bbox=dict(boxstyle='round,pad=1', facecolor='white', edgecolor='#cccccc'))

def listen_for_nodes(sock):
    """
    Background worker:
    1. Grabs raw data from Port 6000
    2. Decodes JSON
    3. Updates the global state variables
    """
    print("[*] Listener thread started...")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
            parsed_data = json.loads(data.decode('utf-8'))
            
            sender = parsed_data.get("sender_port")
            if not sender:
                continue
            
            last_seen[sender] = time.time()
            
            routing_data[sender] = {
                "distances": parsed_data.get("distances_map", {}),
                "next_hops": parsed_data.get("next_hops_map", {})
            }
            
            neighbors_map[sender] = parsed_data.get("neighbours", {})

        except Exception as e:
            # print(f"[!] Listener Error: {e}")
            pass

def main():
    default_port = 6000
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((IP, default_port))
    print(f"[*] Visualizer Socket Bound to {IP}:{default_port}")
    
    listener = threading.Thread(target=listen_for_nodes, args=(sock,), daemon=True)
    listener.start()
    
    fig = plt.figure(figsize=(10, 7))
    ani = FuncAnimation(fig, update_graph, interval=1000, cache_frame_data=False)
    plt.show()
    
if __name__ == "__main__":
    main()