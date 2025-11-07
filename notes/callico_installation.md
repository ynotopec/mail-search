# Callico Deployment Notes

Teklia's official deployment guide for Callico (https://doc.teklia.com/callico/deploy/) relies on Docker Compose to pull the prebuilt image `registry.gitlab.teklia.com/callico/callico:0.6.0`. No Git repository needs to be cloned during installation.

This repository now mirrors that workflow with the helper script [`scripts/install_callico.sh`](../scripts/install_callico.sh). The script simply pulls the published image and boots it with Docker Compose:

```bash
./scripts/install_callico.sh
```

Before running the script, authenticate against Teklia's registry if required:

```bash
docker login registry.gitlab.teklia.com
```

Configuration such as the image tag, exposed port, or admin credentials can be overridden with environment variables (`CALILCO_IMAGE`, `CALILCO_HTTP_PORT`, etc.) or a `.env` file consumed by Docker Compose. The process no longer performs any `git clone` against gitlab.com, aligning the installer with the official documentation.
