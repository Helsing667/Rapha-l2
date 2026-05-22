# Nexus Core - IA Centrale Multi-Plateformes

## Vue d'ensemble

**Nexus Core** est un orchestrateur intelligent conçu pour exécuter des tâches complexes sur un système Linux et piloter à distance des appareils mobiles. Il intègre des protocoles de sécurité stricts et utilise l'API Mistral pour étendre ses capacités via des modèles cloud.

## Architecture

Nexus Core est structuré en quatre couches interdépendantes :

1. **Intent Parser** (`core/intent_parser.py`) : Analyse les requêtes utilisateur en langage naturel
2. **Task Orchestrator** (`core/task_orchestrator.py`) : Décompose les intentions en graphe de tâches exécutables
3. **Execution Engine** (`core/execution_engine.py`) : Exécute les tâches avec mécanismes de rollback
4. **Security Layer** (`core/security_layer.py`) : Supervise l'intégrité et applique les politiques de sécurité

## Prérequis

- **Système** : Linux (noyau 6.2+ recommandé)
- **Python** : 3.10 ou supérieur
- **Accès root** : Requis pour certaines opérations système
- **Dépendances système** :
  - `bubblewrap` ou `firejail` (isolation)
  - `libsodium` (chiffrement)
  - `openssh-client` (communications mobiles)

## Installation

### Installation automatique

```bash
chmod +x setup.sh
./setup.sh
```

### Installation manuelle

1. Installer les dépendances système :
```bash
sudo apt-get install -y bubblewrap libsodium-dev openssh-client
```

2. Installer les dépendances Python :
```bash
pip install -e .
```

3. Pour le support mobile :
```bash
pip install -e ".[mobile]"
```

## Configuration

Le fichier `config.yaml` contient les paramètres modifiables :

- Chemins système
- Seuils de sécurité
- Configuration API Mistral
- Paramètres de connexion mobile

### Configuration de la clé API Mistral

La clé API doit être stockée de manière sécurisée :

```bash
python -c "import keyring; keyring.set_password('nexus_core', 'mistral_api_key', 'VOTRE_CLE_API')"
```

**Ne jamais stocker la clé en clair dans le code ou les fichiers de configuration.**

## Utilisation

### Démarrage

```bash
python main.py
```

### Exemple de requête

```
"Envoie un message WhatsApp à Jean avec le texte 'Réunion demain 10h' et joins-y le fichier /home/user/agenda.pdf"
```

Nexus Core décomposera cette requête en :
1. Vérification de l'existence du fichier
2. Validation des permissions
3. Établissement de la connexion mobile sécurisée
4. Localisation de l'application WhatsApp
5. Envoi du message avec pièce jointe

## Structure du projet

```
nexus-core/
├── main.py                 # Point d'entrée principal
├── config.yaml             # Configuration
├── pyproject.toml          # Gestion des dépendances
├── setup.sh                # Script d'installation
├── README.md               # Ce fichier
├── core/
│   ├── __init__.py
│   ├── intent_parser.py    # Analyse sémantique
│   ├── task_orchestrator.py # Orchestration DAG
│   ├── execution_engine.py # Exécution des tâches
│   └── security_layer.py   # Sécurité et audit
├── utils/
│   ├── __init__.py
│   ├── encryption.py       # Chiffrement (PyNaCl)
│   ├── logging_config.py   # Configuration logging
│   ├── api_wrapper.py      # Wrapper API Mistral
│   └── mobile_client.py    # Client mobile SSH
└── tests/
    ├── __init__.py
    ├── test_intent_parser.py
    ├── test_task_orchestrator.py
    ├── test_execution_engine.py
    └── test_security_layer.py
```

## Sécurité

### Mesures implémentées

- **Isolation** : Conteneurs éphémères via bubblewrap/firejail
- **Chiffrement** : libsodium (PyNaCl) pour les données sensibles
- **Communications** : TLS 1.3, SSH avec authentification par clé
- **API Mistral** : Nonces, timestamps, validation JSON stricte
- **Quorum** : Confirmation explicite pour les actions critiques
- **Logging** : Séparation logs d'audit / opérationnels, chiffrement

### Politiques de moindre privilège

Toutes les opérations sont exécutées avec le niveau de privilège minimum requis :
- `user` : Opérations standards
- `sudo` : Modifications système
- `api` : Appels externes

## Tests

Exécuter la suite de tests :

```bash
pytest tests/ -v
```

Avec couverture de code :

```bash
coverage run -m pytest tests/
coverage report
```

## Intégration Mobile

### Configuration SSH

1. Générer une paire de clés sur le système hôte :
```bash
ssh-keygen -t ed25519 -f ~/.ssh/nexus_mobile
```

2. Copier la clé publique sur l'appareil mobile :
```bash
ssh-copy-id -i ~/.ssh/nexus_mobile.pub user@mobile_ip
```

3. Configurer le tunnel SSH dans `config.yaml`

### Client mobile

Le client mobile (Termux ou équivalent) doit exécuter le serveur JSON-RPC :

```bash
python utils/mobile_client.py --server
```

## Journalisation

Les logs sont séparés en deux catégories :

- **Logs d'audit** (`/var/log/nexus/audit.log`) : Toutes les opérations sensibles
- **Logs opérationnels** (`/var/log/nexus/operations.log`) : Débogage et monitoring

Rotation automatique configurée avec chiffrement.

## Contribution

1. Fork le dépôt
2. Créer une branche de fonctionnalité
3. Exécuter les tests et la vérification de type
4. Soumettre une pull request

## Licence

MIT License - Voir le fichier LICENSE pour plus de détails.

## Avertissement

**Nexus Core** est un outil puissant capable d'exécuter des commandes système. Utilisez-le uniquement dans des environnements contrôlés et avec une compréhension complète des implications de sécurité.
