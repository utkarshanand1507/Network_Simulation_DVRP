import socket
import threading
import time
import json

IP = "127.0.0.1"

def show_routing_table(my_port, distances, next_hops):
    """Displays the RIB and FIB in a clean, perfectly aligned format."""
    print(f"\n--- ROUTING TABLE (Node {my_port}) ---")
    
    # We set strict character widths for the columns (<11 means left-aligned, 11 spaces)
    print(f"{'DESTINATION':<11} | {'DISTANCE':<8} | NEXT HOP")
    
    # Sort by port number so the table is stable
    for dest in sorted(distances.keys()):
        dist = distances[dest]
        hop = next_hops.get(dest)
        
        if dest == hop:
            hop_str = f"Port {hop} (Direct)"
        else:
            hop_str = f"Port {hop}"
            
        # Apply the exact same widths to the variables so they snap to the grid
        print(f"{dest:<11} | {dist:<8} | {hop_str}")
    print("-" * 42)

def broadcast_routing_table(sock, my_port, neighbor_weights, distances, next_hops):
    """Refined Broadcaster with Split Horizon logic."""
    # We now iterate over the keys (ports) of our neighbor_weights dictionary
    for target in neighbor_weights.keys():
        # --- SPLIT HORIZON ---
        # Don't tell a neighbor about a route if they are the one who provided it!
        filtered_table = {}
        for dest, cost in distances.items():
            if next_hops.get(dest) != target:
                filtered_table[dest] = cost
        
        # We always tell them about ourselves
        filtered_table[my_port] = 0

        payload = {
            "type": "heartbeat",
            "sender_port": my_port,
            "routing_table": filtered_table  
        }
        
        json_string = json.dumps(payload)
        try:
            sock.sendto(json_string.encode('utf-8'), (IP, target))
        except Exception:
            pass # Silent fail: just keep running and try again next loop

def grim_reaper(sock, my_port, neighbor_weights, distances, next_hops, timestamps):
    """Patrols for dead nodes and triggers immediate updates."""
    while True:
        current_time = time.time()
        dead_nodes = []
        
        for node, last_seen in list(timestamps.items()):
            if current_time - last_seen > 10:
                dead_nodes.append(node)
                
        if dead_nodes:
            table_changed = False
            for dead_guy in dead_nodes:
                print(f"\n[X] DEAD CONNECTION: Port {dead_guy} flatlined!")
                timestamps.pop(dead_guy, None)
                distances.pop(dead_guy, None)
                next_hops.pop(dead_guy, None)
                neighbor_weights.pop(dead_guy,None)
                # COLLATERAL DAMAGE: Remove routes relying on the dead node
                routes_to_drop = [dest for dest, via in next_hops.items() if via == dead_guy]
                for route in routes_to_drop:
                    distances.pop(route, None)
                    next_hops.pop(route, None)
                table_changed = True
            
            if table_changed:
                show_routing_table(my_port, distances, next_hops)
                print("[!] TRIGGERED UPDATE: Sending emergency gossip.")
                broadcast_routing_table(sock, my_port, neighbor_weights, distances, next_hops)
                    
        time.sleep(1) 

def listen_for_messages(sock, my_port, neighbor_weights, distances, next_hops, timestamps):
    """Processes gossip and implements 'Believe the Provider' logic with weights."""
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            parsed_data = json.loads(data.decode('utf-8'))
            sender = parsed_data.get("sender_port")
            neighbor_map = parsed_data.get("routing_table", {})
            
            if sender is None: continue
            
            # 1. PUNCH THE CLOCK
            timestamps[sender] = time.time()
            table_changed = False 

            # --- THE INFINITE WEIGHT TRICK ---
            if sender not in neighbor_weights:
                # We are hearing from a node we didn't explicitly connect to.
                # Auto-create the return path to keep the Control Plane alive, 
                # but poison the Data Plane with an infinite cost.
                neighbor_weights[sender] = 99999
                print(f"[!] Detected one-way link. Auto-Poisoned return path to Port {sender} (Cost: 99999)")
                
                # Force an update so the Visualizer immediately draws the new poisoned link
                table_changed = True 

            link_weight = neighbor_weights[sender]

            # 2. IMPLICIT WITHDRAWAL
            routes_to_drop = []
            for dest, via_node in list(next_hops.items()):
                if via_node == sender and dest != sender: 
                    if str(dest) not in neighbor_map:
                        routes_to_drop.append(dest)
            
            for route in routes_to_drop:
                distances.pop(route, None)
                next_hops.pop(route, None)
                table_changed = True

           # 3. WEIGHTED BELLMAN-FORD + BELIEVE THE PROVIDER
            
            # Only add the direct neighbor to the routing table if it's a REAL data path
            if link_weight < 99999:
                if sender not in distances or distances[sender] > link_weight:
                    distances[sender] = link_weight
                    next_hops[sender] = sender
                    table_changed = True

            # Distant routes check
            for dest_str, cost in neighbor_map.items():
                dest = int(dest_str)
                if dest == my_port: continue
                
                # --- THE WEIGHT UPGRADE ---
                offered_cost = cost + link_weight
                
                # --- PREVENT POISON LEAK ---
                # If the total cost hits our "infinity" threshold, it's unreachable!
                if offered_cost >= 99999:
                    # If we were relying on this path, drop it entirely
                    if next_hops.get(dest) == sender:
                        distances.pop(dest, None)
                        next_hops.pop(dest, None)
                        table_changed = True
                    continue # Skip adding this toxic route to our table

                # Standard Bellman-Ford check for valid routes
                if (dest not in distances or 
                    offered_cost < distances[dest] or 
                    next_hops.get(dest) == sender):
                    
                    if distances.get(dest) != offered_cost:
                        distances[dest] = offered_cost
                        next_hops[dest] = sender
                        table_changed = True

            if table_changed:
                print(f"\n[+] Map Updated via Port {sender}")
                show_routing_table(my_port, distances, next_hops)
                # Triggered update for fast convergence
                broadcast_routing_table(sock, my_port, neighbor_weights, distances, next_hops)

        except Exception:
            pass

def main():
    my_port = int(input("Enter THIS node's port: "))
    
    # --- UPDATED INPUT PARSER FOR WEIGHTS ---
    raw_ports = input("Enter neighbors as Port:Weight (e.g., 5002:5, 5003:1): ")
    neighbor_weights = {}
    
    if raw_ports.strip():
        for item in raw_ports.split(','):
            parts = item.strip().split(':')
            if len(parts) == 2:
                neighbor_weights[int(parts[0])] = int(parts[1])
            else:
                # Default to weight 1 if user forgets the colon
                neighbor_weights[int(parts[0])] = 1

    distances = {}   
    next_hops = {}   
    timestamps = {}  

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((IP, my_port))

    # Start threads (passing neighbor_weights instead of neighbor_ports)
    threading.Thread(target=listen_for_messages, args=(sock, my_port, neighbor_weights, distances, next_hops, timestamps), daemon=True).start()
    threading.Thread(target=grim_reaper, args=(sock, my_port, neighbor_weights, distances, next_hops, timestamps), daemon=True).start()

    print(f"[*] Node {my_port} active. Running on {IP}. Press Ctrl+C to stop.")
    
    while True:
        #broadcast to all of its nodes in the connection
        broadcast_routing_table(sock, my_port, neighbor_weights, distances, next_hops)
        #broadcast to the visualiser 
        payload = {
            "type": "heartbeat",
            "sender_port": my_port,
            "distances_map":distances,
            "next_hops_map":next_hops,
            "neighbours":neighbor_weights
        }
        json_string = json.dumps(payload)
        try:
            sock.sendto(json_string.encode('utf-8'), (IP, 6000))
        except Exception:
            pass #same thing as the main send function
        time.sleep(3)

if __name__ == "__main__":
    main()