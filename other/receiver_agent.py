import cv2
import mediapipe as mp
import time
import os
import queue
from dotenv import load_dotenv
from discovery_agent import DiscoveryAgent

# Charge les variables d'environnement
load_dotenv()

class ReceiverAgent:
    def __init__(self):
        self.camera_index = int(os.getenv("CAMERA_INDEX", 0))
        self.receive_folder = os.getenv("RECEIVE_FOLDER_PATH", "./received_files")
        self.timeout_waiting = float(os.getenv("TIMEOUT_WAITING_HAND", 5.0))
        
        self.sig_ready = os.getenv("SIG_READY_TO_RECEIVE", "READY_TO_RECEIVE")
        self.sig_cancel = os.getenv("SIG_CANCEL_RECEIVE", "CANCEL_RECEIVE")
        
        # Création du dossier de réception
        os.makedirs(self.receive_folder, exist_ok=True)

        # Initialisation de l'Agent de Découverte
        self.discovery = DiscoveryAgent()
        self.discovery.start()

        # Initialisation MediaPipe (La caméra ne démarre pas encore)
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.mp_draw = mp.solutions.drawing_utils

        # Machine à états : STANDBY -> WAKING_UP -> WAITING_DROP -> DOWNLOADING
        self.state = "STANDBY"
        self.current_sender_ip = None
        self.expected_file = None

    def is_hand_closed(self, hand_landmarks):
        tips_ids = [8, 12, 16, 20] 
        pips_ids = [6, 10, 14, 18]
        fingers_folded = sum(1 for t, p in zip(tips_ids, pips_ids) 
                            if hand_landmarks.landmark[t].y > hand_landmarks.landmark[p].y)
        return fingers_folded >= 3

    def start(self):
        print("💤 Agent Récepteur en veille (STANDBY). Écoute du réseau...")
        
        while True:
            try:
                # Vérifie s'il y a un message réseau (bloque pendant 1 sec, puis recommence)
                alert = self.discovery.alert_queue.get(timeout=1.0)
                
                if alert["signal"] == self.sig_ready and self.state == "STANDBY":
                    print(f"🚨 Signal {self.sig_ready} reçu ! Allumage de la caméra...")
                    self.current_sender_ip = alert["sender_ip"]
                    self.expected_file = alert["file"]
                    self._run_camera_loop()
                    
            except queue.Empty:
                # Rien reçu, on continue de dormir
                pass
            except KeyboardInterrupt:
                print("🛑 Arrêt du récepteur.")
                break

    def _run_camera_loop(self):
        """Boucle vidéo activée uniquement lors d'une alerte."""
        self.state = "WAKING_UP"
        cap = cv2.VideoCapture(self.camera_index)
        wake_up_time = time.time()
        
        print("🎥 Caméra allumée. En attente de la main fermée...")

        while cap.isOpened():
            # 1. Vérification des annulations du Sender en temps réel
            try:
                alert = self.discovery.alert_queue.get_nowait()
                if alert["signal"] == self.sig_cancel:
                    print("❌ Le Sender a annulé le transfert. Extinction de la caméra.")
                    break
            except queue.Empty:
                pass

            # 2. Sécurité : Si l'utilisateur a envoyé le signal mais ne met jamais sa main ici
            if self.state == "WAKING_UP" and (time.time() - wake_up_time > self.timeout_waiting):
                print("⏳ Délai d'attente dépassé (Aucune main détectée). Retour en veille.")
                break

            success, img = cap.read()
            if not success: break

            img = cv2.flip(img, 1)
            results = self.hands.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(img, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                    closed = self.is_hand_closed(hand_landmarks)

                    # --- LOGIQUE DE RECEPTION ---
                    if self.state == "WAKING_UP":
                        if closed:
                            self.state = "WAITING_DROP"
                            print("✊ Main fermée détectée ! Relâchez (ouvrez la main) pour déposer le fichier.")

                    elif self.state == "WAITING_DROP":
                        cv2.putText(img, "Ouvrez la main pour deposer", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        
                        if not closed: # La main vient de s'ouvrir !
                            self.state = "DOWNLOADING"
                            print(f"📥 DÉPÔT DÉTECTÉ ! Demande de transfert pour : {self.expected_file}")
                            
                            # TODO: Implémenter le vrai transfert TCP ici
                            print(f"--> [SIMULATION] Connexion à {self.current_sender_ip} et téléchargement de {self.expected_file}...")
                            time.sleep(1) # Simule le temps de téléchargement
                            print(f"✅ [SIMULATION] Fichier sauvegardé dans {self.receive_folder} !")
                            
                            break # On sort de la boucle vidéo, le transfert est fini
            else:
                if self.state == "WAITING_DROP":
                    cv2.putText(img, "Main perdue !", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            cv2.imshow(f"Receiver - Attente de {self.expected_file}", img)
            if cv2.waitKey(1) & 0xFF == ord('q'): break

        # Nettoyage et retour en veille
        cap.release()
        cv2.destroyAllWindows()
        self.state = "STANDBY"
        self.current_sender_ip = None
        self.expected_file = None
        print("💤 Retour en veille (STANDBY).")

if __name__ == "__main__":
    agent = ReceiverAgent()
    agent.start()