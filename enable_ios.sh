#!/bin/bash
#
# iOS Integration Enable Script for Nexus Core
#
# This script activates the iOS integration module with proper security checks.
# It generates certificates, configures settings, and validates prerequisites.
#
# Usage:
#   ./enable_ios.sh [OPTIONS]
#
# Options:
#   --generate-certs    Generate new certificates
#   --force             Force enable without validation
#   --dry-run           Show what would be done without making changes
#   --help              Show this help message
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.yaml"
CERTS_DIR="${HOME}/.nexus_core/certs"
PENDING_DIR="${HOME}/nexus_core/ios_pending"
IOS_MODULE_DIR="${SCRIPT_DIR}/ios_integration"

# Flags
GENERATE_CERTS=false
FORCE_ENABLE=false
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --generate-certs)
            GENERATE_CERTS=true
            shift
            ;;
        --force)
            FORCE_ENABLE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            head -20 "$0" | tail -15
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    local missing_deps=()
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi
    
    # Check OpenSSL
    if ! command -v openssl &> /dev/null; then
        missing_deps+=("openssl")
    fi
    
    # Check required Python packages
    if ! python3 -c "import yaml" 2>/dev/null; then
        missing_deps+=("python3-yaml (PyYAML)")
    fi
    
    if ! python3 -c "import cryptography" 2>/dev/null; then
        missing_deps+=("python3-cryptography")
    fi
    
    # Optional packages
    if ! python3 -c "import websockets" 2>/dev/null; then
        log_warning "Optional: websockets package not found (needed for WebSocket communication)"
    fi
    
    if ! python3 -c "import nacl" 2>/dev/null; then
        log_warning "Optional: pynacl package not found (needed for ChaCha20-Poly1305 encryption)"
    fi
    
    if [ ${#missing_deps[@]} -ne 0 ]; then
        log_error "Missing dependencies: ${missing_deps[*]}"
        echo ""
        echo "Install with:"
        echo "  sudo apt install python3 openssl"
        echo "  pip install pyyaml cryptography websockets paho-mqtt pynacl"
        echo ""
        
        if [ "$FORCE_ENABLE" = false ]; then
            return 1
        else
            log_warning "Continuing despite missing dependencies (--force flag)"
        fi
    fi
    
    log_success "Prerequisites check passed"
    return 0
}

generate_certificates() {
    log_info "Generating TLS certificates..."
    
    # Create certs directory
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would create directory: ${CERTS_DIR}"
    else
        mkdir -p "${CERTS_DIR}"
        chmod 700 "${CERTS_DIR}"
    fi
    
    # Check if certificates already exist
    if [ -f "${CERTS_DIR}/ca.crt" ] && [ -f "${CERTS_DIR}/server.crt" ]; then
        log_warning "Certificates already exist. Remove them to regenerate."
        read -p "Regenerate anyway? (y/N): " confirm
        if [ "$confirm" != "y" ]; then
            log_info "Skipping certificate generation"
            return 0
        fi
    fi
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would generate CA certificate"
        log_info "[DRY-RUN] Would generate server certificate"
        log_info "[DRY-RUN] Would generate client certificate"
        return 0
    fi
    
    # Generate CA private key and certificate
    log_info "Generating CA keypair (RSA 4096-bit)..."
    openssl genrsa -out "${CERTS_DIR}/ca.key" 4096 2>/dev/null
    openssl req -x509 -new -nodes -key "${CERTS_DIR}/ca.key" \
        -sha256 -days 365 -out "${CERTS_DIR}/ca.crt" \
        -subj "/C=FR/ST=Ile-de-France/L=Paris/O=Nexus Core/CN=Nexus Core CA" \
        2>/dev/null
    log_success "CA certificate generated"
    
    # Generate Server private key and certificate
    log_info "Generating server keypair (RSA 4096-bit)..."
    openssl genrsa -out "${CERTS_DIR}/server.key" 4096 2>/dev/null
    openssl req -new -key "${CERTS_DIR}/server.key" \
        -out "${CERTS_DIR}/server.csr" \
        -subj "/C=FR/ST=Ile-de-France/L=Paris/O=Nexus Core/CN=nexus-core-server" \
        2>/dev/null
    openssl x509 -req -in "${CERTS_DIR}/server.csr" \
        -CA "${CERTS_DIR}/ca.crt" -CAkey "${CERTS_DIR}/ca.key" \
        -CAcreateserial -out "${CERTS_DIR}/server.crt" \
        -days 365 -sha256 \
        -extfile <(echo "subjectAltName=DNS:localhost,IP:127.0.0.1") \
        2>/dev/null
    log_success "Server certificate generated"
    
    # Generate Client private key and certificate (for iOS app)
    log_info "Generating client keypair (RSA 4096-bit)..."
    openssl genrsa -out "${CERTS_DIR}/client.key" 4096 2>/dev/null
    openssl req -new -key "${CERTS_DIR}/client.key" \
        -out "${CERTS_DIR}/client.csr" \
        -subj "/C=FR/ST=Ile-de-France/L=Paris/O=Nexus Core/CN=nexus-core-client" \
        2>/dev/null
    openssl x509 -req -in "${CERTS_DIR}/client.csr" \
        -CA "${CERTS_DIR}/ca.crt" -CAkey "${CERTS_DIR}/ca.key" \
        -CAcreateserial -out "${CERTS_DIR}/client.crt" \
        -days 365 -sha256 2>/dev/null
    log_success "Client certificate generated"
    
    # Set proper permissions
    chmod 600 "${CERTS_DIR}"/*.key
    chmod 644 "${CERTS_DIR}"/*.crt
    
    log_success "All certificates generated successfully"
    echo ""
    echo "Certificate files:"
    ls -la "${CERTS_DIR}/"
    echo ""
    log_warning "IMPORTANT: Securely transfer ca.crt, client.crt, and client.key to your iOS device"
}

update_config() {
    log_info "Updating configuration..."
    
    if [ ! -f "${CONFIG_FILE}" ]; then
        log_error "Configuration file not found: ${CONFIG_FILE}"
        return 1
    fi
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would update ${CONFIG_FILE} with iOS settings"
        return 0
    fi
    
    # Create backup
    cp "${CONFIG_FILE}" "${CONFIG_FILE}.backup.$(date +%Y%m%d%H%M%S)"
    log_info "Configuration backup created"
    
    # Add iOS section if not exists
    if ! grep -q "^ios:" "${CONFIG_FILE}"; then
        cat >> "${CONFIG_FILE}" << EOF

# =============================================================================
# iOS INTEGRATION
# =============================================================================
ios:
  # Module activation (set to true after running this script)
  enabled: false
  
  # Communication settings
  protocol: "websocket"  # websocket or mqtt
  host: "0.0.0.0"
  port: 8443
  use_tls: true
  
  # TLS certificates
  cert_path: "${CERTS_DIR}/server.crt"
  key_path: "${CERTS_DIR}/server.key"
  ca_cert_path: "${CERTS_DIR}/ca.crt"
  client_cert_path: "${CERTS_DIR}/client.crt"
  client_key_path: "${CERTS_DIR}/client.key"
  
  # MQTT specific (if using MQTT)
  mqtt_topic_prefix: "nexus/ios"
  
  # Synchronization
  sync_method: "nas"  # nas, icloud, or direct
  sync_direction: "bidirectional"
  conflict_resolution: "newest_wins"
  pending_dir: "${PENDING_DIR}"
  
  # Security
  enable_attestation: true
  enable_device_check: true
  enable_sandboxing: true
  max_reconnect_attempts: 5
  
  # Resource quotas
  quotas:
    max_cpu_percent: 50
    max_memory_mb: 512
    max_network_kb_per_min: 10240
EOF
        log_success "iOS configuration section added to ${CONFIG_FILE}"
    else
        log_info "iOS configuration section already exists"
    fi
}

create_directories() {
    log_info "Creating required directories..."
    
    if [ "$DRY_RUN" = true ]; then
        log_info "[DRY-RUN] Would create: ${PENDING_DIR}"
        log_info "[DRY-RUN] Would create: ${CERTS_DIR}"
        return 0
    fi
    
    mkdir -p "${PENDING_DIR}"
    mkdir -p "${PENDING_DIR}/archive"
    chmod 700 "${PENDING_DIR}"
    
    log_success "Directories created"
}

validate_setup() {
    log_info "Validating setup..."
    
    local validation_passed=true
    
    # Check certificates exist
    if [ ! -f "${CERTS_DIR}/ca.crt" ]; then
        log_error "CA certificate not found"
        validation_passed=false
    fi
    
    if [ ! -f "${CERTS_DIR}/server.crt" ]; then
        log_error "Server certificate not found"
        validation_passed=false
    fi
    
    # Verify certificates
    if ! openssl verify -CAfile "${CERTS_DIR}/ca.crt" "${CERTS_DIR}/server.crt" 2>/dev/null; then
        log_error "Server certificate verification failed"
        validation_passed=false
    fi
    
    # Check config file
    if [ ! -f "${CONFIG_FILE}" ]; then
        log_error "Configuration file not found"
        validation_passed=false
    fi
    
    # Test iOS module import
    if ! python3 -c "from ios_integration import ios_communication" 2>/dev/null; then
        log_warning "iOS communication module import test failed"
    fi
    
    if [ "$validation_passed" = true ]; then
        log_success "Validation passed"
        return 0
    else
        log_error "Validation failed"
        return 1
    fi
}

show_next_steps() {
    echo ""
    echo "=============================================="
    echo "iOS Integration Setup Complete!"
    echo "=============================================="
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Transfer certificates to your iOS device:"
    echo "   scp ${CERTS_DIR}/ca.crt ${CERTS_DIR}/client.crt ${CERTS_DIR}/client.key user@iphone:/tmp/"
    echo ""
    echo "2. Edit ${CONFIG_FILE} and set:"
    echo "   ios:"
    echo "     enabled: true"
    echo ""
    echo "3. Start Nexus Core with iOS support:"
    echo "   python main.py --interactive"
    echo ""
    echo "4. For detailed setup instructions, see:"
    echo "   ${IOS_MODULE_DIR}/ios_setup_guide.md"
    echo ""
    echo "To disable iOS integration later:"
    echo "   Set 'ios.enabled: false' in ${CONFIG_FILE}"
    echo ""
}

# Main execution
main() {
    echo "=============================================="
    echo "Nexus Core iOS Integration Enable Script"
    echo "=============================================="
    echo ""
    
    # Step 1: Check prerequisites
    if ! check_prerequisites; then
        exit 1
    fi
    
    # Step 2: Generate certificates if requested
    if [ "$GENERATE_CERTS" = true ]; then
        generate_certificates
    fi
    
    # Step 3: Create directories
    create_directories
    
    # Step 4: Update configuration
    update_config
    
    # Step 5: Validate setup
    if ! validate_setup; then
        log_warning "Setup validation had issues, but continuing..."
    fi
    
    # Step 6: Show next steps
    show_next_steps
    
    log_success "iOS integration module is ready for activation"
}

# Run main function
main
