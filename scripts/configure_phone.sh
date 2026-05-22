#!/bin/bash
# Script de configuration de la connexion mobile pour Nexus Core
# Ce script aide à configurer l'adresse IP du téléphone

set -e

echo "=============================================="
echo "Configuration de la connexion mobile Nexus"
echo "=============================================="
echo ""

# Fonction pour afficher les instructions
show_instructions() {
    echo "Pour trouver l'adresse IP de votre téléphone Android :"
    echo ""
    echo "Méthode 1 - Depuis Termux (recommandé):"
    echo "  1. Installez Termux depuis F-Droid"
    echo "  2. Ouvrez Termux et tapez: pkg install openssh"
    echo "  3. Générez une clé: ssh-keygen -t ed25519"
    echo "  4. Démarrez SSH: sshd"
    echo "  5. Trouvez l'IP: ifconfig | grep inet"
    echo ""
    echo "Méthode 2 - Depuis les paramètres Android:"
    echo "  Paramètres > À propos > État > Adresse IP"
    echo ""
    echo "Méthode 3 - Scanner le réseau depuis votre PC:"
    echo "  nmap -sn 192.168.1.0/24"
    echo ""
}

# Vérifier si config.yaml existe
CONFIG_FILE="config.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Erreur: $CONFIG_FILE non trouvé!"
    exit 1
fi

show_instructions

# Demander l'IP du téléphone
read -p "Entrez l'adresse IP de votre téléphone (ex: 192.168.1.42): " PHONE_IP

if [ -z "$PHONE_IP" ]; then
    echo "Aucune IP entrée, annulation."
    exit 0
fi

# Valider le format IP
if [[ ! $PHONE_IP =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    echo "Format d'IP invalide!"
    exit 1
fi

echo ""
echo "IP détectée: $PHONE_IP"
echo ""

# Mettre à jour config.yaml
echo "Mise à jour de $CONFIG_FILE..."

# Utiliser sed pour remplacer les placeholders
sed -i "s/PHONE_IP_ADDRESS/$PHONE_IP/g" "$CONFIG_FILE"

echo "✓ Configuration mise à jour avec succès!"
echo ""
echo "Prochaines étapes:"
echo "1. Sur votre téléphone (Termux):"
echo "   - Installez openssh: pkg install openssh"
echo "   - Générez une clé: ssh-keygen -t ed25519"
echo "   - Copiez la clé publique sur votre PC"
echo "   - Démarrez SSH: sshd"
echo ""
echo "2. Sur votre PC, ajoutez la clé du téléphone:"
echo "   cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys"
echo ""
echo "3. Testez la connexion:"
echo "   ssh -p 8022 u0_a123@$PHONE_IP"
echo ""
echo "4. Lancez Nexus Core:"
echo "   source .venv/bin/activate"
echo "   python main.py --interactive"
echo ""
