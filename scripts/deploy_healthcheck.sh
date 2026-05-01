#!/usr/bin/env bash
set -e

PROJECT="total-now-339022"
REGION="us-west2"
IMAGE="us-west2-docker.pkg.dev/${PROJECT}/mirofish/healthcheck:latest"
JOB_NAME="mirofish-healthcheck"
SCHEDULER_NAME="mirofish-healthcheck-daily"
SA="mirofish-forecast-deploy@${PROJECT}.iam.gserviceaccount.com"

echo "=== Deploying MiroFish Health Check Job ==="
echo ""

# Step 1: Build container
echo "Building container image..."
gcloud builds submit . \
    --project="${PROJECT}" \
    --tag="${IMAGE}" \
    --dockerfile=Dockerfile.healthcheck

# Step 2: Create or update Cloud Run job
echo "Creating/updating Cloud Run job..."
if gcloud run jobs describe "${JOB_NAME}" --project="${PROJECT}" --region="${REGION}" &>/dev/null; then
    gcloud run jobs update "${JOB_NAME}" \
        --project="${PROJECT}" \
        --region="${REGION}" \
        --image="${IMAGE}" \
        --memory=512Mi \
        --cpu=1 \
        --task-timeout=300 \
        --max-retries=1 \
        --service-account="${SA}" \
        --set-secrets="MIROFISH_HEALTHCHECK_EMAIL_FROM=mirofish-healthcheck-email-from:latest,MIROFISH_HEALTHCHECK_EMAIL_PASSWORD=mirofish-healthcheck-email-password:latest,MIROFISH_HEALTHCHECK_EMAIL_TO=mirofish-healthcheck-email-to:latest"
else
    gcloud run jobs create "${JOB_NAME}" \
        --project="${PROJECT}" \
        --region="${REGION}" \
        --image="${IMAGE}" \
        --memory=512Mi \
        --cpu=1 \
        --task-timeout=300 \
        --max-retries=1 \
        --service-account="${SA}" \
        --set-secrets="MIROFISH_HEALTHCHECK_EMAIL_FROM=mirofish-healthcheck-email-from:latest,MIROFISH_HEALTHCHECK_EMAIL_PASSWORD=mirofish-healthcheck-email-password:latest,MIROFISH_HEALTHCHECK_EMAIL_TO=mirofish-healthcheck-email-to:latest"
fi

# Step 3: Create or update Cloud Scheduler job (7 AM CT daily)
echo "Setting up Cloud Scheduler..."
if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --project="${PROJECT}" --location="${REGION}" &>/dev/null; then
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
        --project="${PROJECT}" \
        --location="${REGION}" \
        --schedule="0 7 * * *" \
        --time-zone="America/Chicago" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SA}"
else
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
        --project="${PROJECT}" \
        --location="${REGION}" \
        --schedule="0 7 * * *" \
        --time-zone="America/Chicago" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="${SA}"
fi

echo ""
echo "=== Deployment complete ==="
echo "Job:       gcloud run jobs describe ${JOB_NAME} --project=${PROJECT} --region=${REGION}"
echo "Scheduler: gcloud scheduler jobs describe ${SCHEDULER_NAME} --project=${PROJECT} --location=${REGION}"
echo "Test run:  gcloud run jobs execute ${JOB_NAME} --project=${PROJECT} --region=${REGION} --wait"
