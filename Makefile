SHELL := /bin/bash

HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
VM_NAME ?= workstation-manager-v1
TOOLING_IMAGE ?= workstation-manager-tooling:local
TOOLING_IMAGE_PULL ?= 0
HOST_TEST_WORKERS ?= 2
ANSIBLE_TEST_CACHE_DIR ?=
ANSIBLE_PLAYBOOK_FILES := $(filter-out ansible/inventory.yml,$(wildcard ansible/*.yml))
FIRST_PARTY_COLLECTION_DIRS := \
	ansible/collections/ansible_collections/neilime/workstation_setup \
	ansible/collections/ansible_collections/neilime/workstation_backup \
	ansible/collections/ansible_collections/neilime/workstation_restore \
	ansible/collections/ansible_collections/neilime/workstation_cleanup \
	ansible/collections/ansible_collections/neilime/workstation_state

.PHONY: help setup tool-shell lint lint-fix check-ansible test test-host test-collections ci

help: ## Display help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Build the tooling image or pull the selected CI image
	@if [ "$(TOOLING_IMAGE_PULL)" = "1" ]; then \
		docker image inspect "$(TOOLING_IMAGE)" >/dev/null 2>&1 || docker pull "$(TOOLING_IMAGE)"; \
	else \
		docker build --tag "$(TOOLING_IMAGE)" --file docker/tooling/Dockerfile .; \
	fi

tool-shell: ## Open a shell in the tooling container
	@docker run --rm -it \
		--user "$(HOST_UID):$(HOST_GID)" \
		--env ANSIBLE_HOME=/tmp/.ansible \
		--env ANSIBLE_COLLECTIONS_PATH=/opt/ansible/collections:/workspace/ansible/collections \
		--env HOME=/tmp \
		--env XDG_CACHE_HOME=/tmp/.cache \
		--volume "$(CURDIR):/workspace" \
		--workdir /workspace \
		"$(TOOLING_IMAGE)" \
		bash

lint: ## Run static checks inside the tooling container
	$(call run_linter,)

lint-fix: ## Execute linting and fix
	$(call run_linter, \
		-e FIX_BIOME_FORMAT=true \
		-e FIX_BIOME_LINT=true \
		-e FIX_SPELL_CODESPELL=true \
		-e FIX_MARKDOWN=true \
		-e FIX_MARKDOWN_PRETTIER=true \
		-e FIX_YAML_PRETTIER=true \
		-e FIX_NATURAL_LANGUAGE=true \
		-e FIX_SHELL_SHFMT=true \
		-e FIX_PYTHON_ISORT=true \
		-e FIX_PYTHON_RUFF=true \
		-e FIX_PYTHON_RUFF_FORMAT=true \
		-e FIX_ANSIBLE=true \
	)

check-ansible: ## Run syntax checks inside the tooling container
	$(call tooling,$(check_ansible_command))

test: test-host test-collections ## Run host tests and collection sanity and unit checks

test-host: ## Run isolated host-tool tests with bounded parallelism
	$(call tooling,$(test_host_command))

test-collections: ## Run collection sanity and unit checks
	$(if $(strip $(ANSIBLE_TEST_CACHE_DIR)),@mkdir -p "$(ANSIBLE_TEST_CACHE_DIR)")
	$(call tooling,$(test_collections_command),$(if $(strip $(ANSIBLE_TEST_CACHE_DIR)),--volume "$(abspath $(ANSIBLE_TEST_CACHE_DIR)):/ansible-test-cache"))

ci: setup ## Run the local CI equivalent
	$(MAKE) lint-fix
	$(MAKE) check-ansible
	$(MAKE) test

e2e-up: ## Start the Lima end-to-end test VM
	$(call check_lima)
	@set -e; \
	config_file="$(CURDIR)/e2e-tests/lima-ubuntu.yml"; \
	runtime_config_file="$$(mktemp "/tmp/workstation-manager-lima-XXXXXX.yml")"; \
	trap 'rm -f "$$runtime_config_file"' EXIT; \
	sed 's|location: "."|location: "$(CURDIR)"|' "$$config_file" >"$$runtime_config_file"; \
	if limactl list --format '{{.Name}}' 2>/dev/null | grep -Fxq "$(VM_NAME)"; then \
		limactl start --timeout=20m $(VM_NAME); \
	else \
		limactl start --timeout=20m -y --containerd=none --name=$(VM_NAME) "$$runtime_config_file"; \
	fi

e2e-setup: ## Run workstation.sh setup inside the Lima end-to-end test VM
	$(call check_lima)
	@./e2e-tests/e2e-setup.sh $(VM_NAME)

e2e-backup: ## Run workstation.sh backup inside the Lima end-to-end test VM
	$(call check_lima)
	@./e2e-tests/e2e-backup.sh $(VM_NAME)

e2e-cleanup: ## Run workstation.sh cleanup inside the Lima end-to-end test VM
	$(call check_lima)
	@./e2e-tests/e2e-cleanup.sh $(VM_NAME)

e2e-test: setup ## Run phased backup, setup, and cleanup assertions against the Lima end-to-end test VM
	$(call check_lima)
	@./e2e-tests/e2e-test.sh $(VM_NAME)

e2e-down: ## Stop and remove the Lima end-to-end test VM
	@limactl stop $(VM_NAME) 2>/dev/null || true
	@limactl delete -f $(VM_NAME) 2>/dev/null || true

e2e-reset: e2e-down e2e-up ## Recreate the Lima end-to-end test VM

define run_linter
	DEFAULT_WORKSPACE="$(CURDIR)"; \
	LINTER_IMAGE="linter:latest"; \
	VOLUME="$$DEFAULT_WORKSPACE:$$DEFAULT_WORKSPACE"; \
	docker build --platform=linux/amd64 --build-arg UID=$(shell id -u) --build-arg GID=$(shell id -g) --tag $$LINTER_IMAGE .; \
	docker run \
		--platform=linux/amd64 \
		-v $$VOLUME \
		--rm \
		-e ANSIBLE_CONFIG_FILE=.ansible-lint \
		-e DEFAULT_WORKSPACE="$$DEFAULT_WORKSPACE" \
		-e FILTER_REGEX_EXCLUDE="(^|.*/)(\.cache|\.env|\.git|\.mypy_cache|\.pytest_cache|\.reports[^/]*|\.tmp|__pycache__|venvs|ansible/vars/private\.override\.yml|ansible/vendor-collections|ansible/collections/ansible_collections/community|ansible/collections/ansible_collections/community\.general-[^/]*|ansible/collections/ansible_collections/neilime/[^/]+/tests/output)(/.*)?$$" \
		-e FILTER_REGEX_INCLUDE="$(filter-out $@,$(MAKECMDGOALS))" \
		-e IGNORE_GITIGNORED_FILES=false \
		-e VALIDATE_GIT_COMMITLINT=false \
		$(1) \
		$$LINTER_IMAGE
endef

define tooling
	@docker run --rm \
		--user "$(HOST_UID):$(HOST_GID)" \
		--env ANSIBLE_HOME=/tmp/.ansible \
		--env ANSIBLE_COLLECTIONS_PATH=/opt/ansible/collections:/workspace/ansible/collections \
		--env HOME=/tmp \
		--env XDG_CACHE_HOME=/tmp/.cache \
		--volume "$(CURDIR):/workspace" \
		--workdir /workspace \
		$(2) \
		"$(TOOLING_IMAGE)" \
		bash -lc '$(1)'
endef

define check_ansible_command
	set -e; \
	python3 /workspace/ci/ansible_syntax_report.py \
		--inventory ansible/inventory.yml \
		$(if $(strip $(REPORTS_DIR)),--report-file "/workspace/$(REPORTS_DIR)/checks/ansible-syntax.sarif") \
		$(ANSIBLE_PLAYBOOK_FILES)
endef

define test_host_command
	set -e; \
	python3 -m pytest -q -n "$(HOST_TEST_WORKERS)" -p no:cacheprovider --durations=10 \
		$(if $(strip $(REPORTS_DIR)),--junitxml="/workspace/$(REPORTS_DIR)/tests/e2e-host-tools.junit.xml") \
		/workspace/e2e-tests/unit
endef

define run_collection_test_command
	if [ -n "$(REPORTS_DIR)" ]; then \
		/workspace/ci/run-with-junit.sh \
			"/workspace/$(REPORTS_DIR)/tests/ansible-test-$(1)-$${collection_name}.junit.xml" \
			"ansible-test-$${collection_name}" \
			"$(1)" \
			ansible-test $(1) --python 3.12; \
	else \
		ansible-test $(1) --python 3.12; \
	fi
endef

define test_collections_command
	set -e; \
	$(if $(strip $(ANSIBLE_TEST_CACHE_DIR)),mkdir -p /tmp/.ansible/test; ln -s /ansible-test-cache /tmp/.ansible/test/venv;) \
	for collection_dir in $(FIRST_PARTY_COLLECTION_DIRS); do \
		cd "/workspace/$$collection_dir"; \
		collection_name="$$(basename "$$collection_dir")"; \
		$(call run_collection_test_command,sanity); \
		if [ -d tests/unit ]; then \
			$(call run_collection_test_command,units); \
		fi; \
	done
endef

define check_lima
	@command -v limactl >/dev/null 2>&1 || { echo "limactl is required"; exit 1; }
	@command -v qemu-img >/dev/null 2>&1 || { echo "qemu-img is required"; exit 1; }
	@command -v qemu-system-x86_64 >/dev/null 2>&1 || { echo "qemu-system-x86_64 is required"; exit 1; }
endef

#############################
# Argument fix workaround
#############################
%:
	@:
