#!/bin/bash

# Simple Update Script for TI-E2E-AI
# This script pushes your local changes to the remote server

set -e

# Configuration - UPDATE THESE VALUES
REMOTE_USER="smu"  # Change this to your SSH user
REMOTE_HOST="108.85.14.130"  # Change this to your server IP/domain
REMOTE_PATH="/opt/TI-E2E-AI"  # Change this to your project path on server

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if configuration is set
if [ "$REMOTE_HOST" = "your-server.com" ]; then
    log_error "Please edit this script and set your REMOTE_HOST, REMOTE_USER, and REMOTE_PATH"
    echo "Edit the script and change these lines:"
    echo "REMOTE_USER=\"your-username\""
    echo "REMOTE_HOST=\"your-server-ip-or-domain\""
    echo "REMOTE_PATH=\"/path/to/your/project\""
    exit 1
fi

log_info "Updating TI-E2E-AI on $REMOTE_USER@$REMOTE_HOST..."

# Step 1: Create update package (exclude unnecessary files)
log_info "Creating update package..."
tar --exclude='.git' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='node_modules' \
    --exclude='open-webui/cache' \
    --exclude='open-webui/uploads' \
    --exclude='n8n/database.sqlite*' \
    --exclude='n8n/n8nEventLog*.log' \
    -czf /tmp/ti-e2e-update.tar.gz .

# Step 2: Upload to server
log_info "Uploading to server..."
sshpass -p "abc123" scp /tmp/ti-e2e-update.tar.gz $REMOTE_USER@$REMOTE_HOST:/tmp/

# Step 3: Apply updates on server
log_info "Applying updates on server..."
sshpass -p "abc123" ssh $REMOTE_USER@$REMOTE_HOST << EOF
    cd $REMOTE_PATH
    
    # Backup current state (optional)
    echo "Creating backup..."
    tar -czf backup-\$(date +%Y%m%d-%H%M%S).tar.gz . 2>/dev/null || true
    
    # Extract new files
    echo "Extracting updates..."
    tar -xzf /tmp/ti-e2e-update.tar.gz
    
    # Clean up
    rm /tmp/ti-e2e-update.tar.gz
    
    # Restart services if docker-compose is running
    if docker-compose ps | grep -q "Up"; then
        echo "Restarting services..."
        docker-compose restart
    else
        echo "Services not running, starting them..."
        docker-compose up -d
    fi
    
    echo "Update completed!"
EOF

# Clean up local temp file
rm /tmp/ti-e2e-update.tar.gz

log_success "Update completed successfully!"
echo ""
echo "Your services should now be running with the latest updates."
echo "Check status with: ssh $REMOTE_USER@$REMOTE_HOST 'cd $REMOTE_PATH && docker-compose ps'"
