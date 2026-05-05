import socket
import threading
import time
import json
import os
from dotenv import load_dotenv

# Charge les variables d'environnement depuis le fichier .env
load_dotenv()

class DiscoveryAgent:
    def __init__(self):
        # Récupération des variables du .env
        self.broadcast_port = int(os.getenv("BROADCAST_PORT"))
        self.broadcast_ip = os.getenv("BROADCAST_IP")
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL"))
        self.peer_timeout = int(os.getenv("PEER_TIMEOUT"))
        self.receiver_port = int(os.getenv("RECEIVER_TCP_PORT"))
        
        # Dictionnaire pour stocker les machines actives : { 'IP': timestamp_dernier_contact }
        self.active_peers = {}
        
        # Configuration du socket UDP pour écouter et envoyer sur le réseau
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # On lie le socket au port pour écouter tout ce qui arrive
        self.udp_socket.bind(('', self.broadcast_port))

    def start(self):
        """Lance les threads de l'agent de découverte."""
        print("🚀 Démarrage de l'Agent de Découverte...")
        
        # Thread 1 : Écoute les signaux des autres machines
        listener_thread = threading.Thread(target=self._listen_for_heartbeats, daemon=True)
        listener_thread.start()
        
        # Thread 2 : Envoie notre signal pour dire "je suis en vie"
        broadcaster_thread = threading.Thread(target=self._broadcast_heartbeat, daemon=True)
        broadcaster_thread.start()
        
        # Thread 3 : Nettoie les machines déconnectées
        cleaner_thread = threading.Thread(target=self._cleanup_peers, daemon=True)
        cleaner_thread.start()

    def _broadcast_heartbeat(self):
        """Envoie un signal UDP en broadcast toutes les X secondes."""
        while True:
            # On prépare le message (en JSON pour faciliter la lecture)
            message = {
                "type": "heartbeat",
                "receiver_port": self.receiver_port
            }
            message_bytes = json.dumps(message).encode('utf-8')
            
            try:
                # Envoi du message à tout le réseau (Broadcast)
                self.udp_socket.sendto(message_bytes, (self.broadcast_ip, self.broadcast_port))
                # print(f"💓 Heartbeat envoyé sur le port {self.broadcast_port}")
            except Exception as e:
                print(f"Erreur d'envoi du heartbeat : {e}")
                
            # On attend le prochain battement
            time.sleep(self.heartbeat_interval)

    def _listen_for_heartbeats(self):
        """Écoute en permanence les signaux UDP entrants."""
        print(f"🎧 En écoute sur le port {self.broadcast_port}...")
        while True:
            try:
                # Reception des données (taille max 1024 octets)
                data, addr = self.udp_socket.recvfrom(1024)
                ip_sender = addr[0]
                
                # Optionnel : Ignorer notre propre heartbeat
                # if ip_sender == socket.gethostbyname(socket.gethostname()):
                #    continue

                message = json.loads(data.decode('utf-8'))
                
                # Si c'est bien un heartbeat de notre application
                if message.get("type") == "heartbeat":
                    # On ajoute ou met à jour l'IP avec l'heure exacte de réception
                    self.active_peers[ip_sender] = time.time()
                    print(f"✅ Peer détecté/mis à jour : {ip_sender} (Port cible: {message.get('receiver_port')})")
                    
            except Exception as e:
                print(f"Erreur de réception : {e}")

    def _cleanup_peers(self):
        """Vérifie régulièrement s'il faut supprimer des machines inactives."""
        while True:
            current_time = time.time()
            peers_to_remove = []
            
            # On vérifie chaque machine de notre annuaire
            for ip, last_seen in self.active_peers.items():
                if current_time - last_seen > self.peer_timeout:
                    peers_to_remove.append(ip)
            
            # On supprime celles qui n'ont pas donné signe de vie à temps
            for ip in peers_to_remove:
                del self.active_peers[ip]
                print(f"❌ Peer déconnecté (Timeout) : {ip}")
                
            # Vérification toutes les 10 secondes
            time.sleep(10)

    def get_active_peers(self):
        """Méthode pour récupérer la liste actuelle (utile pour l'Agent Expéditeur)."""
        return list(self.active_peers.keys())


if __name__ == "__main__":
    agent = DiscoveryAgent()
    agent.start()
    
    # Boucle principale pour garder le programme en vie et afficher l'annuaire
    try:
        while True:
            time.sleep(15)
            print(f"Annuaire actuel : {agent.get_active_peers()}")
    except KeyboardInterrupt:
        print("\nArrêt de l'agent.")