#!/bin/bash
# Deployment script for Cloud Run with GCP Secret Manager
#
# Usage:
#   ./quick-deploy.sh           # Build, push, and deploy
#   ./quick-deploy.sh --setup   # First-time secret setup

set -e

PROJECT_ID="spicytool-crud-agent"
REGION="us-central1"
SERVICE_NAME="handler-spicy-crm-agent"
IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/handler-repo/${SERVICE_NAME}:latest"

# Secrets managed via GCP Secret Manager
SECRET_NAMES=("WEBHOOK_SECRET" "AGENT_ENGINE_ID")

# ── Helpers ──────────────────────────────────────────────────────────────────

get_compute_sa() {
    local project_number
    project_number=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
    echo "${project_number}-compute@developer.gserviceaccount.com"
}

secret_exists() {
    gcloud secrets describe "$1" --project="${PROJECT_ID}" &>/dev/null
}

grant_secret_access() {
    local secret_name="$1"
    local sa="$2"
    gcloud secrets add-iam-policy-binding "${secret_name}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${sa}" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet &>/dev/null
    echo "  Granted secretAccessor on ${secret_name} to compute SA"
}

# ── First-time setup ────────────────────────────────────────────────────────

setup_secrets() {
    echo "=== Secret Manager Setup ==="
    echo ""

    # Enable Secret Manager API
    echo "Enabling Secret Manager API..."
    gcloud services enable secretmanager.googleapis.com \
        --project="${PROJECT_ID}" --quiet

    local sa
    sa=$(get_compute_sa)
    echo "Compute SA: ${sa}"
    echo ""

    # WEBHOOK_SECRET
    if secret_exists "WEBHOOK_SECRET"; then
        echo "WEBHOOK_SECRET already exists in Secret Manager."
    else
        local new_secret
        new_secret=$(openssl rand -base64 32)
        echo "Creating WEBHOOK_SECRET..."
        gcloud secrets create WEBHOOK_SECRET \
            --project="${PROJECT_ID}" \
            --replication-policy=automatic
        echo -n "${new_secret}" | gcloud secrets versions add WEBHOOK_SECRET \
            --project="${PROJECT_ID}" --data-file=-
        echo ""
        echo "╔══════════════════════════════════════════════════════════╗"
        echo "║  Your production WEBHOOK_SECRET:                        ║"
        echo "║  ${new_secret}"
        echo "║                                                         ║"
        echo "║  Copy this now — you need it to configure webhook       ║"
        echo "║  clients. It won't be shown again.                      ║"
        echo "╚══════════════════════════════════════════════════════════╝"
        echo ""
    fi
    grant_secret_access "WEBHOOK_SECRET" "${sa}"

    # AGENT_ENGINE_ID
    if secret_exists "AGENT_ENGINE_ID"; then
        echo "AGENT_ENGINE_ID already exists in Secret Manager."
    else
        # Try to read from .env
        local agent_id=""
        if [ -f .env ]; then
            agent_id=$(grep -E '^AGENT_ENGINE_ID=' .env | cut -d'=' -f2-)
        fi

        if [ -z "${agent_id}" ]; then
            echo "AGENT_ENGINE_ID not found in .env."
            read -rp "Enter AGENT_ENGINE_ID: " agent_id
        else
            echo "Found AGENT_ENGINE_ID in .env: ${agent_id}"
            read -rp "Use this value? [Y/n] " confirm
            if [[ "${confirm}" =~ ^[Nn] ]]; then
                read -rp "Enter AGENT_ENGINE_ID: " agent_id
            fi
        fi

        echo "Creating AGENT_ENGINE_ID..."
        gcloud secrets create AGENT_ENGINE_ID \
            --project="${PROJECT_ID}" \
            --replication-policy=automatic
        echo -n "${agent_id}" | gcloud secrets versions add AGENT_ENGINE_ID \
            --project="${PROJECT_ID}" --data-file=-
        echo "AGENT_ENGINE_ID stored in Secret Manager."
    fi
    grant_secret_access "AGENT_ENGINE_ID" "${sa}"

    echo ""
    echo "Setup complete. Run ./quick-deploy.sh to deploy."
}

# ── Handle --setup flag ─────────────────────────────────────────────────────

if [[ "$1" == "--setup" ]]; then
    gcloud config set project "${PROJECT_ID}"
    setup_secrets
    exit 0
fi

# ── Pre-deploy checks ───────────────────────────────────────────────────────

echo "Deploying to Cloud Run..."

# Set project
echo "Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

# Check that secrets exist
for secret in "${SECRET_NAMES[@]}"; do
    if ! secret_exists "${secret}"; then
        echo "ERROR: Secret '${secret}' not found in Secret Manager."
        echo "Run ./quick-deploy.sh --setup first."
        exit 1
    fi
done
echo "All secrets verified in Secret Manager."

# ── Enable APIs ──────────────────────────────────────────────────────────────

echo "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com \
    --quiet 2>/dev/null || true

# ── Artifact Registry ───────────────────────────────────────────────────────

echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create handler-repo \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Docker repository for handler service" 2>/dev/null || echo "Repository already exists"

# ── Build & Push ─────────────────────────────────────────────────────────────

echo "Configuring Docker authentication..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "Building Docker image for linux/amd64 platform..."
docker build --platform linux/amd64 -t "${SERVICE_NAME}:latest" .

echo "Tagging image for Artifact Registry..."
docker tag "${SERVICE_NAME}:latest" "${IMAGE_NAME}"

echo "Pushing Docker image to Artifact Registry..."
docker push "${IMAGE_NAME}"

# ── Deploy ───────────────────────────────────────────────────────────────────

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_NAME}" \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${PROJECT_ID},\
GOOGLE_CLOUD_LOCATION=${REGION}" \
    --set-secrets="\
WEBHOOK_SECRET=WEBHOOK_SECRET:latest,\
AGENT_ENGINE_ID=AGENT_ENGINE_ID:latest" \
    --memory=512Mi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=10

echo ""
echo "Deployment complete!"
echo "Service URL:"
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format="value(status.url)"
