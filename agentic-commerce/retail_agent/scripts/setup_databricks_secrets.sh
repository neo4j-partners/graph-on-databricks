#!/bin/bash
#
# Setup Databricks secrets for the Agentic Commerce agent's Neo4j connection.
# Reads NEO4J_URI and NEO4J_PASSWORD from .env and stores them in Databricks secrets.
#
# Usage:
#   ./retail_agent/scripts/setup_databricks_secrets.sh [--profile PROFILE]
#
#   Examples:
#     ./retail_agent/scripts/setup_databricks_secrets.sh
#     ./retail_agent/scripts/setup_databricks_secrets.sh --profile aws-partner-rk
#
# Prerequisites:
#   - Databricks CLI installed and authenticated (databricks auth login --profile PROFILE)
#   - .env file in the project root with NEO4J_URI and NEO4J_PASSWORD

set -e

# Resolve project root (two levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# Configuration — must match retail_agent.agent.config
SCOPE_NAME="retail-agent-secrets"

# Parse arguments
DATABRICKS_PROFILE=""
PROFILE_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            if [[ -z "${2:-}" ]]; then
                echo "Error: --profile requires a value"
                exit 1
            fi
            DATABRICKS_PROFILE="$2"
            PROFILE_FLAG="--profile $2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1"
            exit 1
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

echo ""
echo "============================================================"
echo "  Databricks Secrets Setup for Agentic Commerce (Neo4j)"
echo "============================================================"
echo ""

log_info "Secret scope: $SCOPE_NAME"
if [[ -n "$DATABRICKS_PROFILE" ]]; then
    log_info "Databricks profile: $DATABRICKS_PROFILE"
fi

# Check for .env file
if [[ ! -f "$ENV_FILE" ]]; then
    log_error ".env file not found at: $ENV_FILE"
    echo ""
    echo "Create a .env file with NEO4J_URI and NEO4J_PASSWORD."
    echo "See .env.sample for an example."
    exit 1
fi

# Read values from .env (handles quotes and inline comments)
read_env() {
    local key=$1
    local value
    value=$(grep "^${key}=" "$ENV_FILE" | head -1 | sed "s/^${key}=//" | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | sed 's/^["'"'"']//' | sed 's/["'"'"']$//')
    echo "$value"
}

NEO4J_URI=$(read_env "NEO4J_URI")
NEO4J_PASSWORD=$(read_env "NEO4J_PASSWORD")

# Validate required values
missing=()
[[ -z "$NEO4J_URI" ]] && missing+=("NEO4J_URI")
[[ -z "$NEO4J_PASSWORD" ]] && missing+=("NEO4J_PASSWORD")

if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "Missing required values in .env: ${missing[*]}"
    echo ""
    echo "Ensure your .env file contains:"
    echo "  NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io"
    echo "  NEO4J_PASSWORD=your-password"
    exit 1
fi

log_info "NEO4J_URI: $NEO4J_URI"
log_info "NEO4J_PASSWORD: [REDACTED - ${#NEO4J_PASSWORD} characters]"

# Check for Databricks CLI
if ! command -v databricks &> /dev/null; then
    log_error "Databricks CLI not found"
    echo ""
    echo "Install with: pip install databricks-cli"
    echo "Or: brew install databricks"
    echo ""
    echo "Then authenticate with: databricks auth login"
    exit 1
fi

# Verify Databricks authentication
log_step "Verifying Databricks CLI authentication..."
if ! databricks auth describe $PROFILE_FLAG &> /dev/null; then
    log_error "Databricks CLI is not authenticated"
    echo ""
    echo "Run: databricks auth login"
    echo "Or configure a profile in ~/.databrickscfg"
    exit 1
fi
log_info "Databricks CLI authenticated"

# Create secret scope (ignore error if already exists)
log_step "Creating secret scope: $SCOPE_NAME"
if databricks secrets create-scope "$SCOPE_NAME" $PROFILE_FLAG 2>/dev/null; then
    log_info "Secret scope created"
else
    log_warn "Secret scope already exists (continuing)"
fi

# Function to set a secret
set_secret() {
    local key=$1
    local value=$2
    log_info "Setting secret: $key"
    echo -n "$value" | databricks secrets put-secret "$SCOPE_NAME" "$key" $PROFILE_FLAG
}

# Set secrets
log_step "Storing Neo4j secrets in Databricks"

set_secret "neo4j-uri" "$NEO4J_URI"
set_secret "neo4j-password" "$NEO4J_PASSWORD"

log_info "All secrets stored"

# Validate
log_step "Validating secrets..."
echo ""
echo "Secrets in scope '$SCOPE_NAME':"
databricks secrets list-secrets "$SCOPE_NAME" $PROFILE_FLAG
echo ""

log_info "Setup complete!"
echo ""
echo "These secrets are used by the Agentic Commerce agent deployment."
echo "See retail_agent.agent.config for the mapping."
echo ""
