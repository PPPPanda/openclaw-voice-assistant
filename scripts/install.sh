#!/bin/bash
# OpenClaw Voice Assistant - Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/PPPPanda/openclaw-voice-assistant/main/scripts/install.sh | bash

set -e

REPO_URL="https://github.com/PPPPanda/openclaw-voice-assistant"
INSTALL_DIR="${HOME}/.openclaw/extensions/voice-assistant"
SPEECH_CORE_PORT="${SPEECH_CORE_PORT:-9001}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# -----------------------------------------------------------------------------
# Pre-flight checks
# -----------------------------------------------------------------------------

log_info "Checking prerequisites..."

# Check Node.js
if ! command -v node &> /dev/null; then
    log_error "Node.js is not installed. Please install Node.js 20+ first."
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 20 ]; then
    log_error "Node.js version 20+ required. Current: $(node -v)"
    exit 1
fi
log_success "Node.js $(node -v) ✓"

# Check Python
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Please install Python 3.11+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    log_error "Python 3.11+ required. Current: Python $PYTHON_VERSION"
    exit 1
fi
log_success "Python $PYTHON_VERSION ✓"

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    log_warn "FFmpeg not found. Audio processing may be limited."
    log_info "Install with: apt install ffmpeg (Linux) or brew install ffmpeg (macOS)"
else
    log_success "FFmpeg ✓"
fi

# Check OpenClaw
if ! command -v openclaw &> /dev/null; then
    log_error "OpenClaw is not installed. Please install it first:"
    echo "  npm install -g openclaw"
    exit 1
fi
log_success "OpenClaw ✓"

# -----------------------------------------------------------------------------
# Installation
# -----------------------------------------------------------------------------

log_info "Installing OpenClaw Voice Assistant..."

# Create installation directory
mkdir -p "$INSTALL_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    log_info "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    log_info "Cloning repository..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# -----------------------------------------------------------------------------
# Install Speech Core (Python)
# -----------------------------------------------------------------------------

log_info "Installing Speech Core service..."

cd "$INSTALL_DIR/speech-core"

# Create virtual environment
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

# Activate and install
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

log_success "Speech Core installed ✓"

# -----------------------------------------------------------------------------
# Install Gateway Plugins (Node.js)
# -----------------------------------------------------------------------------

log_info "Installing Gateway plugins..."

# Speech Core Plugin
cd "$INSTALL_DIR/gateway-plugins/speech-core"
npm install
npm run build
log_success "Speech Core plugin built ✓"

# Discord Voice Plugin
cd "$INSTALL_DIR/gateway-plugins/discord-voice"
npm install
npm run build
log_success "Discord Voice plugin built ✓"

# -----------------------------------------------------------------------------
# Create .env file
# -----------------------------------------------------------------------------

cd "$INSTALL_DIR"

if [ ! -f ".env" ]; then
    cp .env.example .env
    log_info "Created .env file from template"
    log_warn "Please edit $INSTALL_DIR/.env with your configuration"
fi

# -----------------------------------------------------------------------------
# Create systemd service (optional)
# -----------------------------------------------------------------------------

if [ -d "/etc/systemd/system" ] && [ "$(id -u)" -eq 0 ]; then
    cat > /etc/systemd/system/speech-core.service << EOF
[Unit]
Description=OpenClaw Speech Core Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR/speech-core
Environment="PATH=$INSTALL_DIR/speech-core/.venv/bin:\$PATH"
ExecStart=$INSTALL_DIR/speech-core/.venv/bin/python -m speech_core.server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    log_success "Created systemd service: speech-core.service"
fi

# -----------------------------------------------------------------------------
# Print next steps
# -----------------------------------------------------------------------------

echo ""
echo "=============================================="
echo -e "${GREEN}Installation Complete!${NC}"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Configure environment variables:"
echo "   nano $INSTALL_DIR/.env"
echo ""
echo "2. Start Speech Core service:"
echo "   cd $INSTALL_DIR/speech-core"
echo "   source .venv/bin/activate"
echo "   python -m speech_core.server"
echo ""
echo "3. Add plugins to OpenClaw config:"
echo '   plugins:'
echo '     load:'
echo "       paths:"
echo "         - \"$INSTALL_DIR/gateway-plugins/speech-core\""
echo "         - \"$INSTALL_DIR/gateway-plugins/discord-voice\""
echo '     entries:'
echo '       speech-core:'
echo '         enabled: true'
echo '         config:'
echo "           endpoint: \"ws://localhost:$SPEECH_CORE_PORT/speech\""
echo '       discord-voice:'
echo '         enabled: true'
echo '         config:'
echo '           botToken: "YOUR_DISCORD_BOT_TOKEN"'
echo '           guildId: "YOUR_GUILD_ID"'
echo ""
echo "4. Restart OpenClaw Gateway:"
echo "   openclaw gateway restart"
echo ""
echo "Documentation: $REPO_URL#readme"
echo "=============================================="
