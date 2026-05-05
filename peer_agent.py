import cv2
import mediapipe as mp
import time
import os
import queue
import socket
import json
import threading
import shutil
from dotenv import load_dotenv
from discovery_agent import DiscoveryAgent

load_dotenv()

class PeerAgent:
    def __init__(self):
        # Configuration globale
        self.camera_index = int(os.getenv("CAMERA_INDEX", 0))
        self.tmp_folder = os.getenv("TMP_FOLDER_PATH", "./tmp_transfert")
        self.receive_folder = os.getenv("RECEIVE_FOLDER_PATH", "./received_files")
        self.tcp_port = int(os.getenv("TCP_PORT", 8080))
        
        # Délais et marges
        self.time_to_grab = float(os.getenv("TIME_TO_GRAB_SEC", 1.0))
        self.time_to_cancel = float(os.getenv("TIME_TO_CANCEL_SEC", 2.0))
        self.timeout_waiting = float(os.getenv("TIMEOUT_WAITING_HAND", 5.0))
        self.margin = float(os.getenv("OUT_OF_BOUNDS_MARGIN", 0.05))
        
        # Signaux
        self.sig_ready = os.getenv("SIG_READY_TO_RECEIVE", "READY_TO_RECEIVE")
        self.sig_cancel = os.getenv("SIG_CANCEL_RECEIVE", "CANCEL_RECEIVE")
        self.broadcast_port = int(os.getenv("BROADCAST_PORT", 5050))

        self.local_ip = self._get_local_ip()
        print(f"🖥️ IP Locale détectée : {self.local_ip}")

        # Création des dossiers
        os.makedirs(self.tmp_folder, exist_ok=True)
        os.makedirs(self.receive_folder, exist_ok=True)

        # Réseau UDP (Découverte)
        self.discovery = DiscoveryAgent()
        self.discovery.start()

        # Démarrage du Serveur de Fichiers TCP (En arrière-plan)
        threading.Thread(target=self._start_tcp_server, daemon=True).start()

        # MediaPipe
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.mp_draw = mp.solutions.drawing_utils

        # MACHINE À ÉTATS GLOBALE
        self.current_role = "SENDER"
        self.sender_state = "IDLE"
        self.grab_start_time = 0
        self.release_start_time = 0
        self.selected_file_path = None
        
        self.receiver_state = "STANDBY"
        self.expected_file = None
        self.sender_ip = None
        self.receiver_wake_time = 0

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return socket.gethostbyname(socket.gethostname())

    # ==========================================
    # LOGIQUE RÉSEAU TCP : SERVEUR & CLIENT
    # ==========================================
    
    def _start_tcp_server(self):
        """Serveur en arrière-plan qui écoute les demandes de téléchargement."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.tcp_port))
        server.listen(5)
        print(f"🗄️ Serveur de fichiers prêt sur le port {self.tcp_port}")

        while True:
            client, addr = server.accept()
            # Si on a un fichier de sélectionné, on l'envoie
            if self.selected_file_path and os.path.exists(self.selected_file_path):
                file_size = os.path.getsize(self.selected_file_path)
                # 1. Envoi de la taille du fichier (terminé par un saut de ligne)
                client.sendall(f"{file_size}\n".encode('utf-8'))
                
                # 2. Envoi du contenu binaire
                with open(self.selected_file_path, 'rb') as f:
                    while chunk := f.read(4096):
                        client.sendall(chunk)
                print(f"📤 [SERVEUR] Fichier envoyé à {addr[0]}")
            else:
                # 0 indique une erreur ou aucun fichier
                client.sendall(b"0\n") 
            client.close()

    def _download_file(self, ip, filename):
        """Client TCP qui se connecte au SENDER pour récupérer le fichier."""
        try:
            print(f"🔗 [CLIENT] Connexion à {ip}:{self.tcp_port}...")
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect((ip, self.tcp_port))
            
            # Lecture de la taille
            size_str = b""
            while not size_str.endswith(b"\n"):
                size_str += client.recv(1)
            size = int(size_str.decode('utf-8').strip())

            if size == 0:
                print("❌ [CLIENT] Le fichier n'est plus disponible sur la source.")
                return

            save_path = os.path.join(self.receive_folder, filename)
            received = 0
            
            # Réception du fichier par morceaux de 4Ko
            with open(save_path, 'wb') as f:
                while received < size:
                    chunk = client.recv(min(4096, size - received))
                    if not chunk: break
                    f.write(chunk)
                    received += len(chunk)
                    
            print(f"🎉 [CLIENT] SUCCÈS ! Fichier sauvegardé dans : {save_path}")
        except Exception as e:
            print(f"❌ [CLIENT] Erreur de téléchargement : {e}")
        finally:
            # On nettoie l'état pour que la machine puisse renvoyer à son tour
            self.current_role = "SENDER"
            self.sender_state = "IDLE"

    # ==========================================
    # LOGIQUE MEDIA ET VISION
    # ==========================================

    def is_hand_closed(self, hand_landmarks):
        tips_ids = [8, 12, 16, 20] 
        pips_ids = [6, 10, 14, 18]
        fingers_folded = sum(1 for t, p in zip(tips_ids, pips_ids) 
                            if hand_landmarks.landmark[t].y > hand_landmarks.landmark[p].y)
        return fingers_folded >= 3

    def is_hand_out_of_bounds(self, hand_landmarks):
        wrist = hand_landmarks.landmark[0]
        return (wrist.x < self.margin or wrist.x > 1 - self.margin or 
                wrist.y < self.margin or wrist.y > 1 - self.margin)

    def _grab_file_from_tmp(self):
        try:
            items = os.listdir(self.tmp_folder)
            if items:
                item_path = os.path.join(self.tmp_folder, items[0])
                
                # Si c'est un dossier, on le compresse automatiquement en .zip
                if os.path.isdir(item_path):
                    print("📦 [SENDER] Dossier détecté, compression en cours...")
                    shutil.make_archive(item_path, 'zip', item_path)
                    shutil.rmtree(item_path) # On supprime le dossier brut
                    item_path += '.zip'
                    
                self.selected_file_path = item_path
                print(f"✅ [SENDER] Élément prêt pour le transfert : {self.selected_file_path}")
            else:
                self.selected_file_path = None
        except Exception as e:
            print(f"❌ [SENDER] Erreur lecture dossier : {e}")

    def _send_network_signal(self, signal_type):
        peers = self.discovery.get_active_peers()
        if not peers: return

        message = json.dumps({
            "type": "alert",
            "signal": signal_type,
            "file": os.path.basename(self.selected_file_path) if self.selected_file_path else None
        }).encode('utf-8')

        for ip in peers:
            if ip != self.local_ip:
                try:
                    self.discovery.udp_socket.sendto(message, (ip, self.broadcast_port))
                except Exception: pass

    def start(self):
        cap = cv2.VideoCapture(self.camera_index)
        print("🎥 Nœud SMA activé. Rôle par défaut : SENDER.")

        while cap.isOpened():
            # ÉCOUTE DU RÉSEAU (UDP)
            while True:
                try:
                    alert = self.discovery.alert_queue.get_nowait()
                    if alert["sender_ip"] == self.local_ip: continue 

                    if alert["signal"] == self.sig_ready and self.current_role == "SENDER":
                        self.current_role = "RECEIVER"
                        self.receiver_state = "WAKING_UP"
                        self.expected_file = alert["file"]
                        self.sender_ip = alert["sender_ip"]
                        self.receiver_wake_time = time.time()
                    
                    elif alert["signal"] == self.sig_cancel and self.current_role == "RECEIVER":
                        self.current_role = "SENDER"
                        self.sender_state = "IDLE"
                except queue.Empty: break

            # TRAITEMENT VIDÉO
            success, img = cap.read()
            if not success: break
            img = cv2.flip(img, 1)
            results = self.hands.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            
            hand_present = results.multi_hand_landmarks is not None
            closed = False
            out_of_bounds = False

            if hand_present:
                hand_landmarks = results.multi_hand_landmarks[0]
                self.mp_draw.draw_landmarks(img, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                closed = self.is_hand_closed(hand_landmarks)
                out_of_bounds = self.is_hand_out_of_bounds(hand_landmarks)

            # --- SENDER ---
            if self.current_role == "SENDER":
                if hand_present:
                    if self.sender_state == "IDLE":
                        if closed:
                            self.sender_state = "GRABBING"
                            self.grab_start_time = time.time()

                    elif self.sender_state == "GRABBING":
                        if closed:
                            elapsed = time.time() - self.grab_start_time
                            cv2.putText(img, f"Saisie... {elapsed:.1f}s", (10, 50), 1, 2, (0, 165, 255), 2)
                            if elapsed >= self.time_to_grab:
                                self.sender_state = "HOLDING"
                                self._grab_file_from_tmp()
                        else: self.sender_state = "IDLE"

                    elif self.sender_state == "HOLDING":
                        cv2.putText(img, "Fichier en main", (10, 50), 1, 2, (0, 255, 0), 2)
                        if not closed:
                            if self.release_start_time == 0: self.release_start_time = time.time()
                            if time.time() - self.release_start_time >= self.time_to_cancel:
                                self.sender_state = "IDLE"
                                self.selected_file_path = None
                        else:
                            self.release_start_time = 0
                            if out_of_bounds and self.selected_file_path:
                                self.sender_state = "SENDING"
                                self._send_network_signal(self.sig_ready)

                    elif self.sender_state == "SENDING":
                        cv2.putText(img, "ENVOI (En attente de reception)", (10, 50), 1, 2, (255, 0, 255), 2)
                        if not closed:
                            self._send_network_signal(self.sig_cancel)
                            self.sender_state = "IDLE"
                            self.selected_file_path = None
                else:
                    if self.sender_state == "HOLDING" and self.selected_file_path:
                        self.sender_state = "SENDING"
                        self._send_network_signal(self.sig_ready)

            # --- RECEIVER ---
            elif self.current_role == "RECEIVER":
                if time.time() - self.receiver_wake_time > self.timeout_waiting and self.receiver_state == "WAKING_UP":
                    self.current_role = "SENDER"
                    self.sender_state = "IDLE"

                if self.receiver_state == "WAKING_UP":
                    cv2.putText(img, "Fermez la main pour attraper...", (10, 50), 1, 2, (0, 255, 255), 2)
                    if hand_present and closed:
                        self.receiver_state = "WAITING_DROP"

                elif self.receiver_state == "WAITING_DROP":
                    cv2.putText(img, "Ouvrez pour deposer", (10, 50), 1, 2, (0, 255, 0), 2)
                    if hand_present and not closed:
                        self.receiver_state = "DOWNLOADING"
                        cv2.putText(img, "TELECHARGEMENT...", (10, 50), 1, 2, (255, 255, 0), 2)
                        print(f"📥 [RECEIVER] Démarrage du téléchargement...")
                        
                        # 🚀 On lance le téléchargement TCP dans un thread pour ne pas bloquer la caméra !
                        threading.Thread(
                            target=self._download_file, 
                            args=(self.sender_ip, self.expected_file)
                        ).start()

                elif self.receiver_state == "DOWNLOADING":
                    cv2.putText(img, "TELECHARGEMENT EN COURS...", (10, 50), 1, 2, (0, 255, 255), 2)
                    # L'état repassera à SENDER automatiquement quand le thread aura fini (dans _download_file)

            status_text = f"ROLE: {self.current_role}"
            color = (255, 0, 0) if self.current_role == "SENDER" else (0, 0, 255)
            cv2.putText(img, status_text, (img.shape[1] - 250, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.imshow("Hand Transfer - Peer Node", img)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    agent = PeerAgent()
    agent.start()