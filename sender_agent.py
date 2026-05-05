import cv2
import mediapipe as mp
import time
import os
import json
import socket
from dotenv import load_dotenv
from discovery_agent import DiscoveryAgent  # On importe ton agent réseau

# Charge les variables d'environnement
load_dotenv()

class SenderAgent:
    def __init__(self):
        # Configuration depuis .env
        self.camera_index = int(os.getenv("CAMERA_INDEX"))
        self.time_to_grab = float(os.getenv("TIME_TO_GRAB_SEC"))
        self.time_to_cancel = float(os.getenv("TIME_TO_CANCEL_SEC"))
        self.margin = float(os.getenv("OUT_OF_BOUNDS_MARGIN"))
        self.tmp_folder = os.getenv("TMP_FOLDER_PATH")
        
        # Signaux réseau
        self.sig_ready = os.getenv("SIG_READY_TO_RECEIVE")
        self.sig_cancel = os.getenv("SIG_CANCEL_RECEIVE")
        self.broadcast_port = int(os.getenv("BROADCAST_PORT"))

        # Initialisation de l'Agent de Découverte (SMA)
        self.discovery = DiscoveryAgent()
        self.discovery.start() # Lance l'écoute et le heartbeat en arrière-plan

        # Création du dossier temp
        os.makedirs(self.tmp_folder, exist_ok=True)

        # Initialisation MediaPipe
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.mp_draw = mp.solutions.drawing_utils

        # Machine à états
        self.state = "IDLE"
        self.grab_start_time = 0
        self.release_start_time = 0
        self.selected_file_path = None

    def _send_network_signal(self, signal_type):
        """Envoie un signal uniquement aux machines actuellement découvertes."""
        peers = self.discovery.get_active_peers()
        if not peers:
            print("⚠️ Aucun pair détecté sur le réseau. Signal non envoyé.")
            return

        message = json.dumps({
            "type": "alert",
            "signal": signal_type,
            "file": os.path.basename(self.selected_file_path) if self.selected_file_path else None
        }).encode('utf-8')

        # On utilise le socket UDP de l'agent de découverte pour envoyer
        for ip in peers:
            try:
                self.discovery.udp_socket.sendto(message, (ip, self.broadcast_port))
                print(f"📡 Signal {signal_type} envoyé à {ip}")
            except Exception as e:
                print(f"❌ Erreur envoi vers {ip}: {e}")

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
                print(f"✅ Fichier saisi : {self.selected_file_path}")
            else:
                print("❌ Dossier vide.")
                self.selected_file_path = None
        except Exception as e:
            print(f"❌ Erreur lecture dossier : {e}")

    def start(self):
        cap = cv2.VideoCapture(self.camera_index)
        print("🎥 Sender Agent prêt. En attente de mouvement...")

        while cap.isOpened():
            success, img = cap.read()
            if not success: break

            img = cv2.flip(img, 1)
            results = self.hands.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            hand_present = results.multi_hand_landmarks is not None

            if hand_present:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(img, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                    closed = self.is_hand_closed(hand_landmarks)
                    out_of_bounds = self.is_hand_out_of_bounds(hand_landmarks)

                    # --- MACHINE À ÉTATS ---
                    if self.state == "IDLE":
                        if closed:
                            self.state = "GRABBING"
                            self.grab_start_time = time.time()

                    elif self.state == "GRABBING":
                        if closed:
                            elapsed = time.time() - self.grab_start_time
                            cv2.putText(img, f"Saisie... {elapsed:.1f}s", (10, 50), 1, 2, (0, 165, 255), 2)
                            if elapsed >= self.time_to_grab:
                                self.state = "HOLDING"
                                self._grab_file_from_tmp()
                        else:
                            self.state = "IDLE"

                    elif self.state == "HOLDING":
                        cv2.putText(img, "Fichier en main", (10, 50), 1, 2, (0, 255, 0), 2)
                        if not closed:
                            if self.release_start_time == 0: self.release_start_time = time.time()
                            elapsed = time.time() - self.release_start_time
                            cv2.putText(img, f"Annulation {self.time_to_cancel-elapsed:.1f}s", (10, 100), 1, 2, (0, 0, 255), 2)
                            if elapsed >= self.time_to_cancel:
                                self.state = "IDLE"
                                self.selected_file_path = None
                        else:
                            self.release_start_time = 0
                            if out_of_bounds and self.selected_file_path:
                                self.state = "SENDING"
                                self._send_network_signal(self.sig_ready) # ENVOI SIGNAL READY

                    elif self.state == "SENDING":
                        cv2.putText(img, "MODE ENVOI ACTIF", (10, 50), 1, 2, (255, 0, 255), 2)
                        if not closed:
                            if self.release_start_time == 0: self.release_start_time = time.time()
                            elapsed = time.time() - self.release_start_time
                            if elapsed >= self.time_to_cancel:
                                print("❌ Annulation de l'envoi.")
                                self._send_network_signal(self.sig_cancel) # ENVOI SIGNAL CANCEL
                                self.state = "IDLE"
                                self.selected_file_path = None
                        else:
                            self.release_start_time = 0

            else:
                # Si la main disparaît brusquement alors qu'on tient un fichier
                if self.state == "HOLDING" and self.selected_file_path:
                    self.state = "SENDING"
                    self._send_network_signal(self.sig_ready) 

            cv2.imshow("Hand Transfer - Sender", img)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    agent = SenderAgent()
    agent.start()