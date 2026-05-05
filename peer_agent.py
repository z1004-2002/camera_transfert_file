import cv2
import mediapipe as mp
import time
import os
import queue
import socket
import json
from dotenv import load_dotenv
from discovery_agent import DiscoveryAgent

load_dotenv()

class PeerAgent:
    def __init__(self):
        # Configuration globale
        self.camera_index = int(os.getenv("CAMERA_INDEX", 0))
        self.tmp_folder = os.getenv("TMP_FOLDER_PATH", "./tmp_transfert")
        self.receive_folder = os.getenv("RECEIVE_FOLDER_PATH", "./received_files")
        
        # Délais et marges
        self.time_to_grab = float(os.getenv("TIME_TO_GRAB_SEC", 1.0))
        self.time_to_cancel = float(os.getenv("TIME_TO_CANCEL_SEC", 2.0))
        self.timeout_waiting = float(os.getenv("TIMEOUT_WAITING_HAND", 5.0))
        self.margin = float(os.getenv("OUT_OF_BOUNDS_MARGIN", 0.05))
        
        # Signaux
        self.sig_ready = os.getenv("SIG_READY_TO_RECEIVE", "READY_TO_RECEIVE")
        self.sig_cancel = os.getenv("SIG_CANCEL_RECEIVE", "CANCEL_RECEIVE")
        self.broadcast_port = int(os.getenv("BROADCAST_PORT", 5050))

        # Récupération de l'IP locale pour ignorer nos propres messages
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
        
        # Sous-états Sender
        self.sender_state = "IDLE"
        self.grab_start_time = 0
        self.release_start_time = 0
        self.selected_file_path = None
        
        # Sous-états Receiver
        self.receiver_state = "STANDBY"
        self.expected_file = None
        self.sender_ip = None
        self.receiver_wake_time = 0

    def _get_local_ip(self):
        """Astuce pour obtenir la vraie adresse IP locale sur le réseau (même sous Linux)."""
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
                self.selected_file_path = os.path.join(self.tmp_folder, items[0])
                print(f"✅ [SENDER] Fichier saisi : {self.selected_file_path}")
            else:
                self.selected_file_path = None
        except Exception as e:
            print(f"❌ [SENDER] Erreur lecture dossier : {e}")

    def _send_network_signal(self, signal_type):
        peers = self.discovery.get_active_peers()
        if not peers:
            print("⚠️ Aucun pair réseau détecté.")
            return

        message = json.dumps({
            "type": "alert",
            "signal": signal_type,
            "file": os.path.basename(self.selected_file_path) if self.selected_file_path else None
        }).encode('utf-8')

        for ip in peers:
            # Sécurité supplémentaire : On n'envoie pas à nous-même
            if ip != self.local_ip:
                try:
                    self.discovery.udp_socket.sendto(message, (ip, self.broadcast_port))
                except Exception:
                    pass

    def start(self):
        cap = cv2.VideoCapture(self.camera_index)
        print("🎥 Nœud SMA activé. Rôle par défaut : SENDER.")

        while cap.isOpened():
            # --- 1. ÉCOUTE DU RÉSEAU (Lecture de tous les messages en attente) ---
            while True:
                try:
                    alert = self.discovery.alert_queue.get_nowait()
                    
                    # 🛡️ CORRECTION : On ignore nos propres signaux !
                    if alert["sender_ip"] == self.local_ip:
                        continue 

                    if alert["signal"] == self.sig_ready and self.current_role == "SENDER":
                        print(f"🚨 [RÉSEAU] Signal reçu ! Passage en mode RECEPTION pour : {alert['file']}")
                        self.current_role = "RECEIVER"
                        self.receiver_state = "WAKING_UP"
                        self.expected_file = alert["file"]
                        self.sender_ip = alert["sender_ip"]
                        self.receiver_wake_time = time.time()
                    
                    elif alert["signal"] == self.sig_cancel and self.current_role == "RECEIVER":
                        print("❌ [RÉSEAU] Annulation par l'expéditeur. Retour au mode SENDER.")
                        self.current_role = "SENDER"
                        self.sender_state = "IDLE"
                except queue.Empty:
                    break # Plus de messages, on sort de la boucle réseau

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

            # --- 3. LOGIQUE DU RÔLE : SENDER ---
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
                            if out_of_bounds and self.selected_file_path:
                                self.sender_state = "SENDING"
                                print("📡 [SENDER] Envoi du signal READY_TO_RECEIVE")
                                self._send_network_signal(self.sig_ready)

                    elif self.sender_state == "SENDING":
                        cv2.putText(img, "MODE ENVOI ACTIF (En attente...)", (10, 50), 1, 2, (255, 0, 255), 2)
                        
                        # 🛡️ CORRECTION : Annulation immédiate si on relâche sur ce PC
                        if not closed:
                            print("❌ [SENDER] Relâchement sur le PC source. Annulation immédiate.")
                            self._send_network_signal(self.sig_cancel)
                            self.sender_state = "IDLE"
                            self.selected_file_path = None

                else:
                    # La main sort rapidement
                    if self.sender_state == "HOLDING" and self.selected_file_path:
                        self.sender_state = "SENDING"
                        print("📡 [SENDER] Envoi du signal READY_TO_RECEIVE (Main sortie)")
                        self._send_network_signal(self.sig_ready)

            # --- 4. LOGIQUE DU RÔLE : RECEIVER ---
            elif self.current_role == "RECEIVER":
                if time.time() - self.receiver_wake_time > self.timeout_waiting and self.receiver_state == "WAKING_UP":
                    print("⏳ [RECEIVER] Timeout. Retour en mode SENDER.")
                    self.current_role = "SENDER"
                    self.sender_state = "IDLE"

                if self.receiver_state == "WAKING_UP":
                    cv2.putText(img, "Fermez la main pour attraper...", (10, 50), 1, 2, (0, 255, 255), 2)
                    if hand_present and closed:
                        self.receiver_state = "WAITING_DROP"
                        print("✊ [RECEIVER] Main prête ! Ouvrez pour déposer.")

                elif self.receiver_state == "WAITING_DROP":
                    cv2.putText(img, "Ouvrez pour deposer", (10, 50), 1, 2, (0, 255, 0), 2)
                    if hand_present and not closed:
                        print(f"📥 [RECEIVER] TRANSFERT DÉCLENCHÉ pour : {self.expected_file}")
                        # TODO: Vrai transfert TCP ici
                        print("✅ [SIMULATION] Fichier reçu !")
                        
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