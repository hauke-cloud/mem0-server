# Makefile for mem0-server

IMAGE      ?= ghcr.io/hauke-cloud/mem0-server
IMAGE_TAG  ?= dev
CHART_PATH ?= deployment/helm/mem0-server

VENV   ?= .venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python)

# Container engine. podman and docker are interchangeable here.
CONTAINER_ENGINE ?= $(shell command -v docker 2>/dev/null || command -v podman 2>/dev/null)

# The chart's required values, so that lint and template get past `required`.
CHART_REQUIRED := \
	--set oidc.issuer=https://id.example.com/realms/ci \
	--set 'oidc.audiences[0]=mem0' \
	--set mem0.llm.baseUrl=http://llm/v1 \
	--set mem0.llm.model=llm \
	--set mem0.embedder.baseUrl=http://llm/v1 \
	--set mem0.embedder.model=embed

.DEFAULT_GOAL := help

##@ General

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Development

.PHONY: venv
venv: ## Create .venv with runtime and dev dependencies
	python -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt -r requirements-dev.txt

.PHONY: test
test: ## Run the tests
	$(PYTHON) -m pytest

.PHONY: fmt
fmt: ## Format the code
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

.PHONY: fmt-check
fmt-check: ## Fail if any file is unformatted
	$(PYTHON) -m ruff format --check .

.PHONY: lint
lint: ## Run ruff
	$(PYTHON) -m ruff check .

# The shared CI action packages the chart but never lints or renders it, so a
# broken template would otherwise only surface at install time.
.PHONY: helm-lint
helm-lint: ## Lint the chart and render it with every optional feature on
	helm lint $(CHART_PATH) $(CHART_REQUIRED) --set postgres.connectionString=postgresql://ci
	helm template ci $(CHART_PATH) $(CHART_REQUIRED) --set postgres.connectionString=postgresql://ci > /dev/null
	helm template ci $(CHART_PATH) $(CHART_REQUIRED) \
	  --set existingSecret=ci \
	  --set postgres.clientCertSecret=ci \
	  --set persistence.enabled=false \
	  --set mem0.extraConfig.custom_instructions=ci \
	  --set httpRoute.enabled=true \
	  --set ingress.enabled=true \
	  --set envoyGateway.securityPolicy.enabled=true \
	  --set 'envoyGateway.securityPolicy.spec.jwt.providers[0].name=ci' \
	  --set envoyGateway.backendTrafficPolicy.enabled=true \
	  --set envoyGateway.backendTrafficPolicy.spec.timeout.http.requestTimeout=0s > /dev/null

# CI rewrites every "tag:" line in values.yaml to the release version.
.PHONY: tag-guard
tag-guard: ## Fail unless values.yaml has exactly one "tag:" line
	@count="$$(grep -c 'tag:' $(CHART_PATH)/values.yaml)"; \
	  [ "$$count" -eq 1 ] || { echo "values.yaml must contain exactly one 'tag:' line, found $$count" >&2; exit 1; }

.PHONY: ci-lint
ci-lint: fmt-check lint helm-lint tag-guard ## Every lint CI runs, in one target

.PHONY: check
check: fmt ci-lint test ## Everything CI runs on the code

.PHONY: clean
clean: ## Remove caches and packaged charts
	rm -rf .pytest_cache .ruff_cache build dist *.tgz
	find . -name __pycache__ -type d -prune -not -path './$(VENV)/*' -exec rm -rf {} +

##@ Container

.PHONY: image
image: ## Build the container image for the host platform
	$(CONTAINER_ENGINE) build -t $(IMAGE):$(IMAGE_TAG) .
