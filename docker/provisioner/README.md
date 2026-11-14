# Optional Kubernetes sandbox provisioner

Inherited from DeerFlow. This service creates one Pod and NodePort Service per
sandbox. It is optional and is not started by `docker/compose.hilo.yaml`.

Build it with `docker build -t hilo-provisioner docker/provisioner`. Deploy it on
a trusted network accessible to the backend, using Kubernetes in-cluster credentials
or a read-only mounted kubeconfig at `KUBECONFIG_PATH` (default `/root/.kube/config`).
The supplied Dockerfile exposes port 8002. Its `/health` endpoint reports readiness.

Configure these environment variables for your cluster:

| Variable | Purpose |
| --- | --- |
| `K8S_NAMESPACE` | Namespace for sandbox resources (legacy default `deer-flow`) |
| `SANDBOX_IMAGE` | Trusted AIO sandbox image with the sandbox HTTP API |
| `SKILLS_HOST_PATH` | Absolute path on Kubernetes nodes containing Skills |
| `THREADS_HOST_PATH` | Absolute path on nodes containing backend thread data |
| `NODE_HOST` | Node hostname reachable from the backend for NodePort traffic |
| `K8S_API_SERVER` | Optional API server override when kubeconfig uses localhost |
| `KUBECONFIG_PATH` | File path inside the provisioner; a directory is rejected |

Paths refer to the Kubernetes nodes, not necessarily the machine running Compose.
Mount/share the same thread and Skills data as the backend. Configure the backend:

```yaml
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
```

The backend must reach both this service and the returned NodePort URLs. No
cluster credentials or deployment-specific mounts are included in this repository.
Keep this service private: its API manages cluster resources and has no built-in
user authentication. Use restricted cluster permissions, trusted images, and
appropriate network policies. The local regression suite tests kubeconfig handling;
real Kubernetes sandbox creation has not been validated by Hilo's publication audit.
