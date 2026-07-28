# deploying — the phase after this one

Nothing in here has been applied to the cluster yet. The manifests are
written and the images build; what's below is the order that turns
them on.

1. Build and push both images from the repo root:

       docker build -f infrastructure/images/core.Dockerfile   -t registry.k6nis.dev/multirun-core:0.1.0 .
       docker build -f infrastructure/images/runner.Dockerfile -t registry.k6nis.dev/multirun-runner:0.1.0 .
       docker push registry.k6nis.dev/multirun-core:0.1.0
       docker push registry.k6nis.dev/multirun-runner:0.1.0

2. Create the two secrets the chart expects but refuses to own:

       kubectl -n multirun create secret generic multirun-secrets \
           --from-literal=NEON_API_KEY=... \
           --from-literal=RESULTS_DATABASE_URL=...
       multirun creds push          # local subscription creds -> claude-creds

3. `helm install multirun infrastructure/chart` — or apply
   `infrastructure/argocd/application.yaml` and let argocd own it.

4. Prove the cluster loop the same way the local loop was proven:
   `multirun submit core/configs/smoke.yaml --runner-image ...` with a
   single run before any real fan-out.

Open before real use (known, deliberate):

- artifacts land in the pod's emptyDir and die with it — object
  storage (or a PVC) is the first deploy-phase task
- the controller Deployment's command is a placeholder; the watch loop
  that picks up submitted configs comes with it
- private sources need a deploy key for the init container's clone
