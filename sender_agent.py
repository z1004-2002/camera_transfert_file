import cv2
import mediapipe as mp
import time
import os
from dotenv import load_dotenv

# Charge les variables d'environnement
load_dotenv()

class SenderAgent:
    def __init__(self):
        # Récupération des variables du .env
        self.camera_index = int(os.getenv("CAMERA_INDEX"))
        self.time_to_grab = float(os.getenv("TIME_TO_GRAB_SEC"))
        self.time_to_cancel = float(os.getenv("TIME_TO_CANCEL_SEC"))
        self.margin = float(os.getenv("OUT_OF_BOUNDS_MARGIN"))
        self.tmp_folder = os.getenv("TMP_FOLDER_PATH")
        
        # Création du dossier temp s'il n'existe pas
        os.makedirs(self.tmp_folder, exist_ok=True)

        # Initialisation de MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=1, # On ne suit qu'une seule main pour éviter les conflits
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        self.mp_draw = mp.solutions.drawing_utils

        # Machine à états
        self.state = "IDLE" # États possibles : IDLE, GRABBING, HOLDING
        self.grab_start_time = 0
        self.release_start_time = 0

    def is_hand_closed(self, hand_landmarks):
        """
        Détermine si la main est fermée.
        Logique simple : on compare la position du bout des doigts (TIP) 
        avec la jointure du milieu (PIP). Si le bout est plus bas, le doigt est plié.
        """
        # Index des bouts de doigts et des jointures du milieu dans MediaPipe
        tips_ids = [8, 12, 16, 20] # Index, Majeur, Annulaire, Auriculaire
        pips_ids = [6, 10, 14, 18]
        
        fingers_folded = 0
        for tip, pip in zip(tips_ids, pips_ids):
            # En (y), 0 est en haut de l'image, 1 est en bas.
            if hand_landmarks.landmark[tip].y > hand_landmarks.landmark[pip].y:
                fingers_folded += 1
                
        # Si au moins 3 doigts (hors pouce) sont pliés, on considère la main fermée
        return fingers_folded >= 3

    def is_hand_out_of_bounds(self, hand_landmarks):
        """Vérifie si le poignet (point 0) s'approche dangereusement des bords de l'écran."""
        wrist = hand_landmarks.landmark[0]
        return (wrist.x < self.margin or wrist.x > 1 - self.margin or 
                wrist.y < self.margin or wrist.y > 1 - self.margin)

    def start(self):
        """Lance la boucle principale de la caméra."""
        cap = cv2.VideoCapture(self.camera_index)
        print("🎥 Caméra activée. Prêt pour le transfert.")

        while cap.isOpened():
            success, img = cap.read()
            if not success:
                break

            # Miroir de l'image pour que ce soit plus naturel (effet webcam)
            img = cv2.flip(img, 1)
            # Conversion BGR (OpenCV) vers RGB (MediaPipe)
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = self.hands.process(img_rgb)

            hand_present = results.multi_hand_landmarks is not None

            if hand_present:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_draw.draw_landmarks(img, hand_landmarks, self.mp_hands.HAND_CONNECTIONS)
                    
                    closed = self.is_hand_closed(hand_landmarks)
                    out_of_bounds = self.is_hand_out_of_bounds(hand_landmarks)

                    # --- LOGIQUE DE LA MACHINE A ETATS ---
                    
                    if self.state == "IDLE":
                        if closed:
                            self.state = "GRABBING"
                            self.grab_start_time = time.time()
                            print("✊ Main fermée détectée. Tentative de saisie...")

                    elif self.state == "GRABBING":
                        if closed:
                            elapsed = time.time() - self.grab_start_time
                            # Affichage visuel du chargement
                            cv2.putText(img, f"Saisie... {elapsed:.1f}s", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
                            
                            if elapsed >= self.time_to_grab:
                                self.state = "HOLDING"
                                print("📦 Fichier Saisi ! (Sélectionné dans /tmp)")
                                # TODO: Ici, on appellera la fonction de copie de fichier
                        else:
                            self.state = "IDLE" # Annulation car la main s'est ouverte trop tôt

                    elif self.state == "HOLDING":
                        cv2.putText(img, "Fichier en main !", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        
                        if not closed:
                            # Si on lâche la main, on commence le chrono d'annulation
                            if self.release_start_time == 0:
                                self.release_start_time = time.time()
                            
                            elapsed_release = time.time() - self.release_start_time
                            cv2.putText(img, f"Annulation dans... {self.time_to_cancel - elapsed_release:.1f}s", (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                            
                            if elapsed_release >= self.time_to_cancel:
                                self.state = "IDLE"
                                self.release_start_time = 0
                                print("❌ Annulation : Fichier relâché.")
                        else:
                            self.release_start_time = 0 # On referme bien la main, on reset le chrono
                            
                            if out_of_bounds:
                                print("🚀 Main sortie de l'écran avec le fichier !")
                                print("--> ENVOI DU SIGNAL BROADCAST (Mode Réception) <--")
                                self.state = "IDLE" # On reset pour le prochain transfert
                                # TODO: Ici, on fera appel à l'Agent de Découverte pour envoyer le signal réseau

            else:
                # Gérer le cas où la main sort carrément du champ de la caméra brutalement
                if self.state == "HOLDING":
                    print("🚀 Main sortie (non détectée) avec le fichier !")
                    print("--> ENVOI DU SIGNAL BROADCAST (Mode Réception) <--")
                    self.state = "IDLE"
                    # TODO: Envoi du signal réseau

            # Affichage de la vidéo
            cv2.imshow("Hand Transfer - Sender", img)

            # Quitter avec la touche 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    agent = SenderAgent()
    agent.start()