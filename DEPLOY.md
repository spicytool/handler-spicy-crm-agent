# Deployment Guide

## Prerequisites

- [Google Cloud SDK (gcloud CLI)](https://cloud.google.com/sdk/docs/install)
- [Docker](https://docs.docker.com/get-docker/)
- Access to the `spicy-inbound-handler` GCP project
- Authenticated with `gcloud auth login`

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn handler.webhooks:app --reload
```

The server runs on `http://localhost:8000` by default.

## Deploy to Cloud Run

1. Create a `.env` file with required environment variables:

```bash
AGENT_ENGINE_ID=projects/<project-number>/locations/us-central1/reasoningEngines/<engine-id>
```

2. Run the deploy script:

```bash
./quick-deploy.sh
```

The script handles Artifact Registry setup, Docker build (linux/amd64), image push, and Cloud Run deployment.

## Environment Variables

| Variable | Description | Required |
|---|---|---|
| `AGENT_ENGINE_ID` | Vertex AI Agent Engine resource ID | Yes |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID (set by deploy script) | Auto |
| `GOOGLE_CLOUD_LOCATION` | GCP region (set by deploy script) | Auto |
| `PORT` | Server port (set by Cloud Run) | Auto |

## Health Check

After deployment, verify the service is running:

```bash
SERVICE_URL=$(gcloud run services describe handler-spicy-crm-agent \
    --region us-central1 --format="value(status.url)")

curl "${SERVICE_URL}/health"
```
