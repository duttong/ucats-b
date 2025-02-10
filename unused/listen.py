import socket
import select

# Define the ports to listen on
#PORTS = [7075, 50555]
PORTS = [50555]

# Create UDP sockets and bind them
sockets = []
for port in PORTS:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))  # Listen on all available network interfaces
    sockets.append(sock)

print(f"Listening for UDP data on ports {PORTS}...")

try:
    while True:
        # Use select to monitor multiple sockets for incoming data
        readable, _, _ = select.select(sockets, [], [])
        
        for sock in readable:
            data, addr = sock.recvfrom(1024)  # Receive up to 1024 bytes
            print(f"Received from {addr} on port {sock.getsockname()[1]}: {data.decode('utf-8', errors='ignore')}")
except KeyboardInterrupt:
    print("\nStopping UDP listener.")
finally:
    # Close sockets
    for sock in sockets:
        sock.close()