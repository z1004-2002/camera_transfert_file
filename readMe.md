# 🖐️ Hand Gesture File Transfer

An innovative interactive Peer-to-Peer (P2P) file transfer system, entirely controlled by gesture recognition. This project relies on the **Multi-Agent Systems (MAS)** paradigm to handle network discovery, visual recognition, and binary transfer in a decentralized and asynchronous manner.

## ✨ Features

* **Physical "Drag & Drop" Input:** Close your hand in front of the camera to "grab" a file, move your hand out of the frame, and open it on another computer to "drop" it.
* **Automatic Network Discovery (UDP):** Nodes automatically discover each other on the local network via a passive "Heartbeat" system. No central server is required.
* **Secure Transfer (TCP):** Once the transfer intention is validated by gestures, the file is transferred without data loss via a TCP socket.
* **Robust State Machine:** Smooth handling of cancellations (if the user releases the file too early or cancels the movement).
* **Unified P2P Architecture:** Each machine runs the same code and dynamically switches between Sender (`SENDER`) and Receiver (`RECEIVER`) roles.

---

## 🛠️ Prerequisites

* **Python 3.8** or higher.
* A functional **Webcam**.
* Two computers connected to the **same local network** (Wi-Fi or Ethernet).

---

## 🚀 Installation and Setup

### 1. Clone the project
```bash
git clone <YOUR_REPOSITORY_URL>
cd <FOLDER_NAME>
```

### 2. Create a virtual environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

Create a `requirements.txt` file if it doesn't already exist containing these lines, then install them:

```Plaintext
python-dotenv==1.0.0
opencv-python==4.8.1.78
mediapipe==0.10.7
```

```bash
pip install -r requirements.txt
```

### 4. Configuration (The .env file)

Create a file named `.env` at the root of the project and paste the following configuration:

```Code snippet
# .env

# Network configuration for the Multi-Agent System
BROADCAST_PORT=5050
BROADCAST_IP=255.255.255.255

# Time configuration (in seconds)
HEARTBEAT_INTERVAL=30
PEER_TIMEOUT=45

# TCP/UDP Ports
RECEIVER_TCP_PORT=8080
TCP_PORT=8080

# Network Signals
SIG_PULL_FILE=PULL_FILE
SIG_READY_TO_RECEIVE=READY_TO_RECEIVE
SIG_CANCEL_RECEIVE=CANCEL_RECEIVE

# Camera and Sender Agent configuration
CAMERA_INDEX=0
TIME_TO_GRAB_SEC=0.5
TIME_TO_CANCEL_SEC=1.0
OUT_OF_BOUNDS_MARGIN=0.05
TIMEOUT_WAITING_HAND=5.0

# Folder paths (Automatically created on launch)
TMP_FOLDER_PATH=./tmp_transfer
RECEIVE_FOLDER_PATH=./received_files
```

---

## 🎮 How to use it? (The Choreography)

1. Place a file you want to send into the `./tmp_transfer `folder of Computer A.
2. Run the program on both computers:

```bash
python peer_agent.py
```

1. On Computer A (Sender):
   * Hold your open hand in front of the camera.
   * Close your hand (as if grabbing an object). Keep it closed for 0.5s. The system will grab the file from the `./tmp_transfer` folder.
   * Move your closed hand out of the camera's field of view. The system switches to "`ACTIVE SEND MODE`" and alerts the network.
2. On Computer B (Receiver):
   * The screen displays that a signal has been received and asks you to close your hand.
   * Hold your closed hand in front of the camera.
   * Open your hand (as if dropping an object).
3. Transfer: The TCP transfer is triggered. The file will appear in the `./received_files` folder of Computer B!

💡 Cancellation tip: If you change your mind during step 3, simply bring your hand back into the camera frame of Computer A and open it. The transfer will be instantly canceled.

---

## 🧠 System Architecture (MAS)

The project is divided into two main components that collaborate asynchronously:

1. `discovery_agent.py` (The Network Agent)
   * Runs in the background using threads (`threading`).
   * Sends UDP broadcasts every 30 seconds ("I am alive").
   * Maintains a dynamic directory of active peers on the network.
   * Intercepts alert signals (`READY`, `CANCEL`, `PULL`) and passes them to the main node via a queue (`queue.Queue`).

2. `peer_agent.py` (The Peer Node / Video Logic)
   * Manages the OpenCV video stream and MediaPipe Hands processing.
   * Implements a finite state machine (`IDLE`, `GRABBING`, `HOLDING`, `SENDING`, `WAKING_UP`, `WAITING_DROP`).
   * Dynamically switches roles (`SENDER` ↔ `RECEIVER`) based on physical events (gestures) and network events (signals from the discovery agent).
   * Handles connections and binary file transfers via TCP (`socket`).