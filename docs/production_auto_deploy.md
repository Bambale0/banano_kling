# Production auto deploy

The workflow `.github/workflows/deploy-production.yml` deploys every successful
push to `tanyapi` to the production backend host.

Deployment order:

1. wait for the matching `CI — Tanya TG Bot` run;
2. refuse deployment when that CI run is not successful;
3. connect to the production host with a pinned SSH host key;
4. refuse deployment when tracked local repository changes exist;
5. fetch and reset the server checkout to the exact GitHub commit SHA;
6. run `scripts/deploy_backend_docker.sh deploy`;
7. verify Docker health and the image revision label;
8. print Docker/systemd diagnostics when a deployment fails.

The existing deploy script creates a database backup and restores the systemd
service automatically when the Docker health check fails.

## Required repository secrets

Create these under repository Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `PROD_SSH_HOST` | Public IPv4 address or DNS name of the backend server |
| `PROD_SSH_PRIVATE_KEY` | Private ED25519 key used only by GitHub Actions |
| `PROD_SSH_KNOWN_HOSTS` | Pinned OpenSSH known-hosts line for the production host |
| `PROD_SSH_USER` | Optional, defaults to `root` |
| `PROD_SSH_PORT` | Optional, defaults to `22` |
| `PROD_PROJECT_PATH` | Optional, defaults to `/root/tanya/banano_kling` |

When both `PROD_SSH_HOST` and `PROD_SSH_PRIVATE_KEY` are absent, deployment is
reported as disabled and the workflow exits successfully. A partially configured
set of secrets fails explicitly.

## Create a dedicated Actions key on the server

Run as the account that GitHub Actions will use, currently `root`:

```bash
install -d -m 0700 ~/.ssh
ssh-keygen -t ed25519 \
  -f ~/.ssh/github-actions-banano \
  -N '' \
  -C 'github-actions-banano-production'
cat ~/.ssh/github-actions-banano.pub >> ~/.ssh/authorized_keys
chmod 0600 ~/.ssh/authorized_keys
```

Put the full output of this command into `PROD_SSH_PRIVATE_KEY`:

```bash
cat ~/.ssh/github-actions-banano
```

After the secret has been saved, remove the private copy from the server:

```bash
shred -u ~/.ssh/github-actions-banano 2>/dev/null || rm -f ~/.ssh/github-actions-banano
```

Keep the `.pub` file for auditing or remove it after confirming that its content
is present in `authorized_keys`.

## Pin the server host key

For port 22 and a host stored in `$HOST`, create the known-hosts value from the
server's existing ED25519 host public key:

```bash
HOST='SERVER_PUBLIC_IP_OR_DNS'
printf '%s %s\n' "$HOST" "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"
```

For a non-standard SSH port:

```bash
HOST='SERVER_PUBLIC_IP_OR_DNS'
PORT='2222'
printf '[%s]:%s %s\n' "$HOST" "$PORT" "$(cat /etc/ssh/ssh_host_ed25519_key.pub)"
```

Save exactly that line as `PROD_SSH_KNOWN_HOSTS`. The workflow deliberately does
not use `StrictHostKeyChecking=no` and does not trust a live `ssh-keyscan` result.

## First activation

After all secrets have been added, push a commit to `tanyapi`. The deployment
workflow will wait for CI and then perform the first Docker cutover.

The host must already contain:

- the repository at `PROD_PROJECT_PATH`;
- `.env` and optional `.env.postgres`;
- Docker with the Compose plugin;
- the existing `banano-kling.service` for automatic rollback during first cutover.

## Emergency rollback

On the server:

```bash
cd /root/tanya/banano_kling
sudo bash scripts/deploy_backend_docker.sh rollback
```

To stop automatic deployment immediately, remove or rename `PROD_SSH_HOST` or
`PROD_SSH_PRIVATE_KEY` in repository Actions secrets.
