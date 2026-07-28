# deploying

Two repos own this:

- **this one** — the images, the chart (the deployable shape), and the
  harness that runs inside them. ArgoCD syncs `infrastructure/chart`
  straight from here (read-only deploy key; the repository credential
  is a SealedSecret in kubeden's `platform/argocd`).
- **kubeden/kubeden** — `k8s-cluster-configuration/applications/multirun/`:
  the Application itself (his app-of-apps pattern, two sources) and the
  SealedSecrets, which are sealed against his cluster and so live
  beside it, not here.

Nothing reaches the cluster except through that Application. No
`kubectl apply`, ever — if it isn't in kubeden/kubeden, it doesn't
exist.

## images

`.github/workflows/build-push.yml` builds both images on every push to
main and on dispatch: `registry.k6nis.dev/multirun-core` and
`multirun-runner`, tagged with the short sha (`:latest` only from
main). Registry creds are the repo secrets `REGISTRY_USERNAME` /
`REGISTRY_PASSWORD`, same as the other a2wio repos.

Shipping a new build is a gitops commit, not a rollout command: pin the
new sha in `chart/values.yaml` on main, sync. Nothing to re-render,
nowhere else to update.

## secrets

Four secrets in the `multirun` namespace carry credentials. Three are
static and live in git as SealedSecrets — encrypted for this cluster's
sealed-secrets controller, safe to commit, useless anywhere else:

- `multirun-secrets` (NEON_API_KEY, RESULTS_DATABASE_URL) — sealed in
  kubeden/kubeden beside the Application
- `source-deploy-key` (read-only deploy key for private task sources) —
  sealed, same place
- `registry-credentials` — not ours at all: a kyverno policy clones it
  into every namespace from its sealed source

To rotate a sealed one: build the Secret locally, run it through
`kubeseal` against the cluster, commit the new blob. Plaintext never
lands in any repo.

The fourth, `claude-creds`, rotates on its own schedule and is NEVER a
git object — a sealed blob would just be a stale credential with extra
steps. It gets in exactly one way: `multirun creds push` from a
logged-in machine, which copies the local claude login into the Secret
by hand. The controller watches the access token's expiry; when it
gets close it runs one no-op CLI turn — the CLI refreshes its own
token — and pushes the rotated file back into the Secret. The log
speaks only when something changed or actually broke: a turn that
fails auth means the refresh token is dead, and THAT line is loud, so
"why are runs failing auth" is answered by
`kubectl logs deploy/multirun-core`, not by archaeology. When it
fires, `multirun creds push` from a logged-in machine resets the
world.

## the controller

The Deployment runs `multirun watch /etc/multirun` — the loop that
picks up published fanouts (see the design doc). Submitting work is

    multirun publish core/configs/<config>.yaml

which renders the config (task source resolved, validated) into the
`multirun-config` ConfigMap with a fresh stamp. The stamp names the
instance; the results db remembers which instances already ran, so a
controller restart re-runs nothing.

Artifacts land on the `multirun-artifacts` PVC (`local-path`, one
node), one dir per run; the controller writes the db diffs into the
same dir at harvest and records `meta.json` into the results db. The
PVC is the raw copy — the queryable truth is the results db.

## proving it

Same ladder as always, one rung at a time:

1. `multirun local core/configs/smoke.yaml` — the loop, no cluster
2. `multirun publish core/configs/smoke.yaml` — the loop, on the
   cluster, one run
3. a real fan-out

## still open (known, deliberate)

- the runner's ServiceAccount has no RBAC and must keep having none
- `ttlSecondsAfterFinished` reaps finished Jobs after an hour; the
  artifacts and the results db are the record, not the Job objects
- artifacts accumulate on the PVC until pruned by hand (5Gi is weeks
  of fan-outs; a retention sweep can come with the dashboard)
