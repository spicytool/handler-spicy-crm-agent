# Deployment Guide

## Prerequisites

- [Google Cloud SDK (gcloud CLI)](https://cloud.google.com/sdk/docs/install)
- [Docker](https://docs.docker.com/get-docker/)
- Access to the `spicytool-crud-agent` GCP project
- Authenticated with `gcloud auth login`

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn handler.webhooks:app --reload
```

The server runs on `http://localhost:8000` by default.

## First-Time Setup (Secret Manager)

Before your first deploy, create the secrets in GCP:

```bash
./quick-deploy.sh --setup
```

This will:
1. Enable the Secret Manager API
2. Create `WEBHOOK_SECRET` with a cryptographic random value (printed once — copy it)
3. Create `AGENT_ENGINE_ID` (reads from `.env` or prompts you)
4. Grant the compute service account `secretAccessor` on both secrets

## Deploy to Cloud Run

```bash
./quick-deploy.sh
```

The script verifies secrets exist, builds the Docker image (linux/amd64), pushes to Artifact Registry, and deploys to Cloud Run with secrets injected from Secret Manager.

## Environment Variables

| Variable | Source | Sensitive | Description |
|---|---|---|---|
| `WEBHOOK_SECRET` | Secret Manager | Yes | Bearer token for webhook auth |
| `AGENT_ENGINE_ID` | Secret Manager | Yes | Vertex AI Agent Engine resource ID |
| `GOOGLE_CLOUD_PROJECT` | Plain env var | No | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Plain env var | No | GCP region |
| `PORT` | Cloud Run | No | Server port (auto-set) |

## Rotating Secrets

To rotate a secret (e.g., `WEBHOOK_SECRET`):

```bash
# Generate a new value
NEW_SECRET=$(openssl rand -base64 32)
echo "New WEBHOOK_SECRET: ${NEW_SECRET}"

# Add as a new version (previous version is preserved)
echo -n "${NEW_SECRET}" | gcloud secrets versions add WEBHOOK_SECRET \
    --project=spicytool-crud-agent --data-file=-

# Redeploy to pick up the new version
./quick-deploy.sh
```

Update any webhook clients with the new secret value.

To rotate `AGENT_ENGINE_ID`:

```bash
echo -n "projects/<project>/locations/us-central1/reasoningEngines/<new-id>" | \
    gcloud secrets versions add AGENT_ENGINE_ID \
    --project=spicytool-crud-agent --data-file=-

./quick-deploy.sh
```

## Health Check

After deployment, verify the service is running:

```bash
SERVICE_URL=$(gcloud run services describe handler-spicy-crm-agent \
    --region us-central1 --format="value(status.url)")

curl "${SERVICE_URL}/health"
```
