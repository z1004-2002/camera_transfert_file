# 🖐️ Hand Gesture File Transfer

Un système innovant de transfert de fichiers de Pair-à-Pair (P2P) interactif, entièrement contrôlé par la reconnaissance gestuelle. Ce projet s'appuie sur le paradigme des **Systèmes Multi-Agents (SMA)** pour gérer la découverte réseau, la reconnaissance visuelle et le transfert binaire de manière décentralisée et asynchrone.

## ✨ Fonctionnalités

* **Saisie "Drag & Drop" Physique :** Fermez la main devant la caméra pour "attraper" un fichier, sortez la main de l'écran, et ouvrez-la sur un autre ordinateur pour le "déposer".
* **Découverte Réseau Automatique (UDP) :** Les nœuds se découvrent automatiquement sur le réseau local via un système de "Heartbeat" (battements de cœur) passif. Aucun serveur central n'est requis.
* **Transfert Sécurisé (TCP) :** Une fois l'intention de transfert validée par les gestes, le fichier est transféré sans perte de données via un socket TCP.
* **Machine à États Robuste :** Gestion fluide des annulations (si l'utilisateur relâche le fichier trop tôt ou annule le mouvement).
* **Architecture P2P Unifiée :** Chaque machine exécute le même code et bascule dynamiquement entre les rôles d'Expéditeur (`SENDER`) et de Récepteur (`RECEIVER`).

---

## 🛠️ Prérequis

* **Python 3.8** ou supérieur.
* Une **Webcam** fonctionnelle.
* Deux ordinateurs connectés au **même réseau local** (Wi-Fi ou Ethernet).

---

## 🚀 Installation et Démarrage

### 1. Cloner le projet
```bash
git clone <URL_DE_TON_DEPOT>
cd <NOM_DU_DOSSIER>
```

### 2. Créer un environnement virtuel (Recommandé)

```bash
python3 -m venv venv
source venv/bin/activate  # Sur Windows : venv\Scripts\activate
```

### 3. Installer les dépendances

Créez un fichier `requirements.txt` si cela n'existe pas déjà contenant ces lignes, puis installez-les :

```Plaintext
python-dotenv==1.0.0
opencv-python==4.8.1.78
mediapipe==0.10.7
```

```bash
pip install -r requirements.txt
```

### 4. Configuration (Le fichier .env)

Créez un fichier nommé `.env` à la racine du projet et collez-y la configuration suivante :

```Code snippet
# .env

# Configuration du réseau pour le Système Multi-Agents
BROADCAST_PORT=5050
BROADCAST_IP=255.255.255.255

# Configuration des temps (en secondes)
HEARTBEAT_INTERVAL=30
PEER_TIMEOUT=45

# Ports TCP/UDP
RECEIVER_TCP_PORT=8080
TCP_PORT=8080

# Signaux Réseau
SIG_PULL_FILE=PULL_FILE
SIG_READY_TO_RECEIVE=READY_TO_RECEIVE
SIG_CANCEL_RECEIVE=CANCEL_RECEIVE

# Configuration de la Caméra et de l'Agent Expéditeur
CAMERA_INDEX=0
TIME_TO_GRAB_SEC=0.5
TIME_TO_CANCEL_SEC=1.0
OUT_OF_BOUNDS_MARGIN=0.05
TIMEOUT_WAITING_HAND=5.0

# Chemins des dossiers (Créés automatiquement au lancement)
TMP_FOLDER_PATH=./tmp_transfer
RECEIVE_FOLDER_PATH=./received_files
```

## 🎮 Comment l'utiliser ? (La Chorégraphie)

1. Placez un fichier que vous souhaitez envoyer dans le dossier `./tmp_transfer` de l'Ordinateur A.
2. Lancez le programme sur les deux ordinateurs :
```bash
python peer_agent.py
```

3. Sur l'Ordinateur A (Expéditeur) :
   * Présentez votre main ouverte devant la caméra.
   * Fermez la main (comme pour attraper un objet). Maintenez-la fermée pendant 0.5s. Le système va saisir le fichier du dossier `./tmp_transfer`.
   * Sortez votre main fermée du champ de vision de la caméra. Le système passe en `"MODE ENVOI ACTIF"` et alerte le réseau.
4. Sur l'Ordinateur B (Récepteur) :
   * L'écran affiche qu'un signal est reçu et vous demande de fermer la main.
   * Présentez votre main fermée dans la caméra.
   * Ouvrez la main (comme pour lâcher un objet).
5. Transfert : Le transfert TCP se déclenche. Le fichier apparaîtra dans le dossier `./received_files` de l'Ordinateur B !

💡 Astuce d'annulation : Si vous changez d'avis pendant l'étape 3, ramenez simplement votre main dans le cadre de la caméra de l'Ordinateur A et ouvrez-la. Le transfert sera instantanément annulé.

## 🧠 Architecture du Système (SMA)
Le projet est divisé en deux composants principaux qui collaborent de manière asynchrone :

1. discovery_agent.py (L'Agent de Réseau)
   * Fonctionne en arrière-plan avec des threads (`threading`).
   * Envoie des broadcasts UDP toutes les 30 secondes ("Je suis en vie").
   * Maintient un annuaire dynamique des pairs actifs sur le réseau.
   * Intercepte les signaux d'alerte (`READY`, `CANCEL`, `PULL`) et les transmet au nœud principal via une file d'attente (`queue.Queue`).

2. peer_agent.py (Le Nœud Pair / Logique Vidéo)
   * Gère le flux vidéo OpenCV et le traitement MediaPipe Hands.
   * Implémente une machine à états finis (`IDLE`, `GRABBING`, `HOLDING`, `SENDING`, `WAKING_UP`, `WAITING_DROP`).
   * Change dynamiquement de rôle (`SENDER` ↔ `RECEIVER`) en fonction des événements physiques (gestes) et réseau (signaux de l'agent de découverte).
   * Gère les connexions et transferts de fichiers binaires via TCP (`socket`).