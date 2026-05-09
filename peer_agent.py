import cv2
import mediapipe as mp
import time
import os
import queue
import socket
import json
import threading
from dotenv import load_dotenv
from discovery_agent import DiscoveryAgent

load_dotenv()

class PeerAgent:
    def __init__(self):
        # Configuration globale
        self.camera_index = int(os.getenv("CAMERA_INDEX"))
        self.tmp_folder = os.getenv("TMP_FOLDER_PATH")
        self.receive_folder = os.getenv("RECEIVE_FOLDER_PATH")
        
        # Délais et marges
        self.time_to_grab = float(os.getenv("TIME_TO_GRAB_SEC"))
        self.time_to_cancel = float(os.getenv("TIME_TO_CANCEL_SEC"))
        self.timeout_waiting = float(os.getenv("TIMEOUT_WAITING_HAND"))
        self.margin = float(os.getenv("OUT_OF_BOUNDS_MARGIN"))
        
        # Signaux & TCP
        self.sig_ready = os.getenv("SIG_READY_TO_RECEIVE")
        self.sig_cancel = os.getenv("SIG_CANCEL_RECEIVE")
        self.sig_pull = os.getenv("SIG_PULL_FILE")
        self.broadcast_port = int(os.getenv("BROADCAST_PORT"))
        self.tcp_port = int(os.getenv("TCP_PORT"))

        # Récupération de l'IP locale
        self.local_ip = self._get_local_ip()
        print(f"🖥️ IP Locale détectée : {self.local_ip}")

        # Création des dossiers
        os.makedirs(self.tmp_folder, exist_ok=True)
        os.makedirs(self.receive_folder, exist_ok=True)

        # Réseau
        self.discovery = DiscoveryAgent()
        self.discovery.start()

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

    def is_hand_closed(self, hand_landmarks):
        tips_ids = [8, 12, 16, 20] 
        pips_ids = [6, 10, 14, 18]
        fingers_folded = sum(1 for t, p in zip(tips_ids, pips_ids) if hand_landmarks.landmark[t].y > hand_landmarks.landmark[p].y)
        return fingers_folded >= 3

    def is_hand_out_of_bounds(self, hand_landmarks):
        wrist = hand_landmarks.landmark[0]
        return (wrist.x < self.margin or wrist.x > 1 - self.margin or 
                wrist.y < self.margin or wrist.y > 1 - self.margin)

    def _grab_file_from_tmp(self):
        try:
            items = os.listdir(self.tmp_folder)
            if items:
                self.selected_file_path = os.path.join(self.tmp_folder, items[0])
                print(f"✅ [SENDER] Fichier saisi : {self.selected_file_path}")
            else:
                self.selected_file_path = None
        except Exception as e:
            print(f"❌ [SENDER] Erreur lecture dossier : {e}")

    def _send_network_signal(self, signal_type, file_name=None):
        peers = self.discovery.get_active_peers()
        if not peers: return

        message = json.dumps({
            "type": "alert",
            "signal": signal_type,
            "file": file_name
        }).encode('utf-8')

        for ip in peers:
            if ip != self.local_ip:
                try:
                    self.discovery.udp_socket.sendto(message, (ip, self.broadcast_port))
                except Exception:
                    pass

    # ==========================================
    # 🚀 NOUVELLES FONCTIONS DE TRANSFERT TCP
    # ==========================================
    
    def _send_file_tcp(self, receiver_ip, file_path):
        """SENDER: Connecte et envoie le fichier par TCP."""
        try:
            print(f"🔗 [SENDER] Connexion TCP à {receiver_ip}:{self.tcp_port}...")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((receiver_ip, self.tcp_port))
                with open(file_path, 'rb') as f:
                    print(f"🚀 [SENDER] Transfert de '{os.path.basename(file_path)}' en cours...")
                    s.sendall(f.read())
            print("✅ [SENDER] Fichier transféré avec succès !")
            
            # Optionnel : Supprimer le fichier du /tmp après envoi
            # os.remove(file_path)
        except Exception as e:
            print(f"❌ [SENDER] Échec du transfert TCP : {e}")

    def _receive_file_tcp(self, expected_file_name):
        """RECEIVER: Ouvre un port et attend le fichier."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('0.0.0.0', self.tcp_port))
                s.listen(1)
                s.settimeout(10.0) # On attend le sender pendant 10 secondes max
                
                print(f"🎧 [RECEIVER] Port TCP {self.tcp_port} ouvert. En attente du fichier...")
                conn, addr = s.accept()
                
                with conn:
                    save_path = os.path.join(self.receive_folder, expected_file_name)
                    print(f"📥 [RECEIVER] Réception des données depuis {addr[0]}...")
                    
                    with open(save_path, 'wb') as f:
                        while True:
                            data = conn.recv(4096) # Lecture par blocs de 4Ko
                            if not data:
                                break
                            f.write(data)
                    print(f"✅ [RECEIVER] Fichier sauvegardé sous : {save_path}")
        except socket.timeout:
            print("⏳ [RECEIVER] Timeout TCP : L'expéditeur ne s'est pas connecté.")
        except Exception as e:
            print(f"❌ [RECEIVER] Erreur serveur TCP : {e}")

    # ==========================================
    # BOUCLE PRINCIPALE
    # ==========================================

    def start(self):
        cap = cv2.VideoCapture(self.camera_index)
        print("🎥 Nœud SMA activé. Rôle par défaut : SENDER.")

        while cap.isOpened():
            # --- 1. ÉCOUTE DU RÉSEAU ---
            while True:
                try:
                    alert = self.discovery.alert_queue.get_nowait()
                    if alert["sender_ip"] == self.local_ip: continue 

                    # RECEIVER entend l'alerte
                    if alert["signal"] == self.sig_ready and self.current_role == "SENDER":
                        print(f"🚨 [RÉSEAU] Signal reçu ! Passage en RECEPTION pour : {alert['file']}")
                        self.current_role = "RECEIVER"
                        self.receiver_state = "WAKING_UP"
                        self.expected_file = alert["file"]
                        self.sender_ip = alert["sender_ip"]
                        self.receiver_wake_time = time.time()
                    
                    # RECEIVER entend l'annulation
                    elif alert["signal"] == self.sig_cancel and self.current_role == "RECEIVER":
                        print("❌ [RÉSEAU] Annulation par l'expéditeur.")
                        self.current_role = "SENDER"
                        self.sender_state = "IDLE"
                        
                    # SENDER entend l'appel du Récepteur pour envoyer le fichier !
                    elif alert["signal"] == self.sig_pull and self.current_role == "SENDER" and self.sender_state == "SENDING":
                        print("🔥 [RÉSEAU] Le récepteur est prêt ! Lancement du transfert...")
                        receiver_ip = alert["sender_ip"]
                        
                        # On lance l'envoi dans un Thread séparé pour ne pas bloquer la caméra
                        threading.Thread(target=self._send_file_tcp, args=(receiver_ip, self.selected_file_path)).start()
                        
                        self.sender_state = "IDLE"
                        self.selected_file_path = None

                except queue.Empty:
                    break

            # --- 2. TRAITEMENT VIDÉO ---
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

            # --- 3. LOGIQUE SENDER ---
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
                        else:
                            self.sender_state = "IDLE"

                    elif self.sender_state == "HOLDING":
                        cv2.putText(img, "Fichier en main", (10, 50), 1, 2, (0, 255, 0), 2)
                        if not closed:
                            if self.release_start_time == 0: self.release_start_time = time.time()
                            elapsed = time.time() - self.release_start_time
                            cv2.putText(img, f"Annulation {self.time_to_cancel-elapsed:.1f}s", (10, 100), 1, 2, (0, 0, 255), 2)
                            if elapsed >= self.time_to_cancel:
                                self.sender_state = "IDLE"
                                self.selected_file_path = None
                        else:
                            self.release_start_time = 0
                            # if out_of_bounds and self.selected_file_path:
                            if self.selected_file_path:
                                self.sender_state = "SENDING"
                                file_name = os.path.basename(self.selected_file_path)
                                print(f"📡 [SENDER] Envoi signal READY_TO_RECEIVE pour {file_name}")
                                self._send_network_signal(self.sig_ready, file_name)

                    elif self.sender_state == "SENDING":
                        cv2.putText(img, "MODE ENVOI ACTIF", (10, 50), 1, 2, (255, 0, 255), 2)
                        if not closed:
                            if self.release_start_time == 0: self.release_start_time = time.time()
                            elapsed = time.time() - self.release_start_time
                            cv2.putText(img, f"Annulation {self.time_to_cancel-elapsed:.1f}s", (10, 100), 1, 2, (0, 0, 255), 2)
                            if elapsed >= self.time_to_cancel:
                                self.sender_state = "IDLE"
                                self.selected_file_path = None
                                print("❌ [SENDER] Relâchement local. Annulation.")
                                self._send_network_signal(self.sig_cancel)
                                self.selected_file_path = None
                        else:
                            self.release_start_time = time.time()

                else:
                    if self.sender_state == "HOLDING" and self.selected_file_path:
                        self.sender_state = "SENDING"
                        file_name = os.path.basename(self.selected_file_path)
                        print(f"📡 [SENDER] Envoi signal READY_TO_RECEIVE pour {file_name} (Main sortie)")
                        self._send_network_signal(self.sig_ready, file_name)

            # --- 4. LOGIQUE RECEIVER ---
            elif self.current_role == "RECEIVER":
                if time.time() - self.receiver_wake_time > self.timeout_waiting and self.receiver_state == "WAKING_UP":
                    print("⏳ [RECEIVER] Timeout. Retour en mode SENDER.")
                    self.current_role = "SENDER"

                if self.receiver_state == "WAKING_UP":
                    cv2.putText(img, "Fermez la main pour attraper...", (10, 50), 1, 2, (0, 255, 255), 2)
                    if hand_present and closed:
                        self.receiver_state = "WAITING_DROP"
                        print("✊ [RECEIVER] Main prête ! Ouvrez pour déposer.")

                elif self.receiver_state == "WAITING_DROP":
                    cv2.putText(img, "Ouvrez pour deposer", (10, 50), 1, 2, (0, 255, 0), 2)
                    if hand_present and not closed:
                        print(f"📥 [RECEIVER] Dépôt détecté ! Ouverture du port TCP...")
                        
                        # 1. On lance le serveur TCP en arrière-plan
                        threading.Thread(target=self._receive_file_tcp, args=(self.expected_file,)).start()
                        
                        # 2. On crie au Sender d'envoyer la sauce
                        self._send_network_signal(self.sig_pull)
                        
                        # 3. Le job vidéo est fini, on retourne écouter le Sender
                        self.current_role = "SENDER"
                        self.sender_state = "IDLE"

            # --- AFFICHAGE ---
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