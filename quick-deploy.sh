#!/bin/bash
# Quick deployment script for Cloud Run

set -e

PROJECT_ID="spicy-inbound-handler"
REGION="us-central1"
SERVICE_NAME="handler-spicy-crm-agent"
IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/handler-repo/${SERVICE_NAME}:latest"

echo "Deploying to Cloud Run..."

# Set project
echo "Setting project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

# Enable APIs (if not already enabled)
echo "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --quiet 2>/dev/null || true

# Create Artifact Registry repository (if it doesn't exist)
echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create handler-repo \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Docker repository for handler service" 2>/dev/null || echo "Repository already exists"

# Configure Docker auth
echo "Configuring Docker authentication..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build Docker image for Cloud Run
# IMPORTANT: Use --platform linux/amd64 for Cloud Run compatibility (required on Mac/ARM)
echo "Building Docker image for linux/amd64 platform..."
docker build --platform linux/amd64 -t "${SERVICE_NAME}:latest" .

# Tag image for Artifact Registry
echo "Tagging image for Artifact Registry..."
docker tag "${SERVICE_NAME}:latest" "${IMAGE_NAME}"

# Push to Artifact Registry
echo "Pushing Docker image to Artifact Registry..."
docker push "${IMAGE_NAME}"

# Load env vars from .env (gitignored)
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# AGENT_ENGINE_ID must be set in .env or exported before running this script
# Example: AGENT_ENGINE_ID=projects/<number>/locations/us-central1/reasoningEngines/<id>
if [ -z "${AGENT_ENGINE_ID}" ]; then
    echo "ERROR: AGENT_ENGINE_ID not set. Add it to .env or export it."
    echo "  echo 'AGENT_ENGINE_ID=projects/<number>/locations/us-central1/reasoningEngines/<id>' >> .env"
    exit 1
fi

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image "${IMAGE_NAME}" \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --set-env-vars="\
GOOGLE_CLOUD_PROJECT=${PROJECT_ID},\
GOOGLE_CLOUD_LOCATION=${REGION},\
AGENT_ENGINE_ID=${AGENT_ENGINE_ID}" \
    --memory=512Mi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=10

echo "Deployment complete!"
echo "Service URL:"
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format="value(status.url)"
