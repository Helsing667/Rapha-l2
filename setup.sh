#!/bin/bash
# Script d'installation automatique de Nexus Core
# Ce script installe toutes les dépendances système et Python requises

set -e  # Arrêter en cas d'erreur

echo "========================================="
echo "Nexus Core - Installation Automatique"
echo "========================================="

# Vérifier que nous sommes sur Linux
if [[ "$(uname)" != "Linux" ]]; then
    echo "ERREUR: Nexus Core nécessite un système Linux"
    exit 1
fi

# Vérifier la version du noyau
KERNEL_VERSION=$(uname -r | cut -d'-' -f1)
REQUIRED_VERSION="6.2"
if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$KERNEL_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
    echo "ATTENTION: Noyau recommandé >= 6.2, version actuelle: $KERNEL_VERSION"
fi

# Vérifier la version de Python
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_PYTHON="3.10"
if [[ "$(printf '%s\n' "$REQUIRED_PYTHON" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_PYTHON" ]]; then
    echo "ERREUR: Python >= 3.10 requis, version actuelle: $PYTHON_VERSION"
    exit 1
fi

echo "[1/5] Mise à jour des dépôts..."
sudo apt-get update -qq

echo "[2/5] Installation des dépendances système..."
sudo apt-get install -y -qq \
    bubblewrap \
    libsodium-dev \
    openssh-client \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libffi-dev \
    libssl-dev \
    git \
    curl

echo "[3/5] Création de l'environnement virtuel..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Environnement virtuel créé dans .venv/"
else
    echo "Environnement virtuel déjà existant"
fi

echo "[4/5] Activation et installation des dépendances Python..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q

# Installation optionnelle du support mobile
read -p "Installer le support mobile (paramiko, asyncssh) ? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "[5/5] Installation des dépendances mobiles..."
    pip install -e ".[mobile]" -q
else
    echo "[5/5] Support mobile ignoré"
fi

echo ""
echo "========================================="
echo "Installation terminée avec succès !"
echo "========================================="
echo ""
echo "Pour activer l'environnement virtuel :"
echo "  source .venv/bin/activate"
echo ""
echo "Pour configurer la clé API Mistral :"
echo "  python -c \"import keyring; keyring.set_password('nexus_core', 'mistral_api_key', 'VOTRE_CLE')\""
echo ""
echo "Pour démarrer Nexus Core :"
echo "  python main.py"
echo ""
