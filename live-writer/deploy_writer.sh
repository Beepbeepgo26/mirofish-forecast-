#!/usr/bin/env bash
set -e

# Prompt user for secrets
echo "=== Deploying Databento Live Writer ==="
echo ""
echo "Please enter your Databento API Key (starts with db-):"
read -s DATABENTO_API_KEY

echo "Please enter your Upstash Redis URL (e.g. https://...):"
read REDIS_URL

echo "Please enter your Upstash Redis Token:"
read -s REDIS_TOKEN

echo "Building and submitting to Artifact Registry..."
gcloud builds submit . \
    --project=total-now-339022 \
    --tag=us-west2-docker.pkg.dev/total-now-339022/mirofish/live-writer:latest

echo "Deploying to Cloud Run with min-instances=1..."
gcloud run deploy mirofish-live-writer \
    --project=total-now-339022 \
    --region=us-west2 \
    --image=us-west2-docker.pkg.dev/total-now-339022/mirofish/live-writer:latest \
    --min-instances=1 \
    --max-instances=1 \
    --memory=256Mi \
    --cpu=1 \
    --timeout=3600 \
    --no-allow-unauthenticated \
    --set-env-vars="DATABENTO_API_KEY=${DATABENTO_API_KEY},REDIS_URL=${REDIS_URL},REDIS_TOKEN=${REDIS_TOKEN}"

echo "Deployment complete! Status will be available in GCP Console."
