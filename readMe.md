# Camera file transfert

## Objectif

faire le transfert de fichier à partir de la détection du movement de la main fermé vers un autre machine, un repertoire défini. En mettant en avant le concept des SMA.

## Which type of agent will I choose ? and why using agent ?

## Étape de mise en place du element

1. Mise en place du réseau
2. Agent de découverte du réseau
   1. synchronisation du réseau (la listes des IP/port de tous le réseau), les ip sur lequel tourne ce code
   2. Toutes les 30 secondes, chaque agent sur le réseau envoie un petit message broadcastChaque 30s, l'agent vérifie si les ip:port sont toujours accéssible
3. Concevoir l'agent de transfert
   1. définir le déclancheur (la main qui se ferme sur la camera avec un écart de > 1s)
   2. la lecture du mouvement par le capteur (camera)
   3. controle de la souris avec le doigt
   4. sélection de l'élement à envoyer
      1. Détecter la sorti de la sortie de la main fermé de la camera (changement d'état de la main other -> fermé)
      2. envoyer un signal dans le réseau qui va activer le mode reception dans l'agent de reception (broadcast)
      3. Pas la sélection de la souris mais défini un element dans le repertoire /tmp dans lequel copier le fichier
      4. control si l'élement existe déjà et ne le copie pas à nouveau
      5. Si on sélectionne et on sélectionne sur un autre element du réseau ça choisi le dernier element à être transféré
      6. si on lache avant de sortir, ça désélectionne (délais>2s)
   5. Sortir la main du capteur étant fermé (non détection)
   6. Attente du signal pour envoyer le fichier. (va t'on définier un protocol d'envoie de fichier ??)
      1. Si la main est de retour et fermé sur l'écran et on relache, le fichier est déselectionné, envoie du message de fermeture de la reception
4. Concevoir l'agent de reception
   1. Reception du signal et activation de la détection (La camera) et fermeture du mode de détection
   2. Détection d'une main fermé qui entre dans la camera (avec un délais de < 1s)
   3. Changement d'état de la main (fermé -> ouvert)
   4. Envoyer un signal au sender de transférer,
   5. Reception du fichier
   6. Envoi du signal d'arrêt d'envoie.
      1. Si le sender envoie plutôt le message de fermeture, on arrête la reception


## Install this

```sudo
sudo apt-get update
sudo apt-get install python3-tk python3-dev scrot xsel xclip
sudo apt-get install xclip

```
