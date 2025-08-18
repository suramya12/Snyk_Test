# Vulnerable Multi-Stack Demo (for Snyk)

This repository intentionally contains insecure code and outdated dependencies to trigger Snyk's detectors across SCA, SAST, IaC, and container analysis. **Do not deploy**.

## Components
- **node-api**: Express app with several insecure endpoints and vulnerable deps (lodash/minimist).
- **python-service**: Flask app with YAML deserialization and shell injection, vulnerable deps (PyYAML/Jinja2).
- **java-app**: Simple Java app with vulnerable dependencies (log4j-core 2.14.1, commons-collections 3.2.1) and insecure patterns (deserialization, TrustAll SSL).
- **iac**: Terraform with risky defaults (0.0.0.0/0 SSH, public S3).
- **Dockerfiles**: outdated base images and root user.

## Snyk commands
```bash
snyk auth
snyk code test
snyk iac test iac/
# SCA by ecosystem
snyk test --file=node-api/package.json --package-manager=npm
snyk test --file=python-service/requirements.txt --package-manager=pip
snyk test --file=java-app/pom.xml --package-manager=maven
# Container / Dockerfile
snyk container test Dockerfile.node
snyk container test Dockerfile.python
```

## Legal / Safety
This is for educational scanning only. Do not expose to the internet, do not deploy to production, and do not use these patterns in real software.
