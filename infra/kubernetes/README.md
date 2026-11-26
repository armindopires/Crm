# Kubernetes (base, não aplicada)

Base Kustomize mínima com os controlos de segurança esperados: não-root, filesystem read-only, sem
capabilities, probes e limites de recursos. **Não há overlays de ambiente nem Terraform**: o fornecedor cloud,
o cluster, o ingress, o gestor de segredos e o GitOps (Argo CD/Flux) estão **NAO_INDICADO** (ver STATUS).
Os segredos são referenciados por `secretRef` e devem vir de um operador de cofre (External Secrets/Vault),
nunca de manifests versionados.

Validação local: `kubectl kustomize infra/kubernetes/base` (não executado neste ambiente: kubectl indisponível).
