Frontend production deployment is guarded by `.github/workflows/deploy-frontend-production.yml`.

The workflow validates on GitHub-hosted runners first, falls back to the `nuromix`
self-hosted runner for trusted pushes, deploys the exact tested SHA to the remote
frontend host, and verifies the deployed static export and public health endpoints.
