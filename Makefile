SHELL := /bin/bash

HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
VM_NAME ?= workstation-manager-v1
TOOLING_IMAGE ?= workstation-manager-tooling:local
TOOLING_IMAGE_PULL ?= 0
ANSIBLE_PLAYBOOK_FILES := $(filter-out ansible/inventory.yml,$(wildcard ansible/*.yml))
FIRST_PARTY_COLLECTION_DIRS := \
	ansible/collections/ansible_collections/neilime/workstation_setup \
	ansible/collections/ansible_collections/neilime/workstation_backup \
	ansible/collections/ansible_collections/neilime/workstation_cleanup \
	ansible/collections/ansible_collections/neilime/workstation_state

.PHONY: help

help: ## Display help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Build or verify the tooling image
	@if docker image inspect "$(TOOLING_IMAGE)" >/dev/null 2>&1; then \
		echo "tooling image available: $(TOOLING_IMAGE)"; \
	elif [ "$(TOOLING_IMAGE_PULL)" = "1" ]; then \
		docker pull "$(TOOLING_IMAGE)"; \
	else \
		docker build --tag "$(TOOLING_IMAGE)" --file docker/tooling/Dockerfile .; \
	fi

tool-shell: ## Open a shell in the tooling container
	@docker run --rm -it \
		--user "$(HOST_UID):$(HOST_GID)" \
		--env ANSIBLE_HOME=/tmp/.ansible \
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
		-e FIX_JSON_PRETTIER=true \
		-e FIX_JAVASCRIPT_PRETTIER=true \
		-e FIX_YAML_PRETTIER=true \
		-e FIX_MARKDOWN=true \
		-e FIX_MARKDOWN_PRETTIER=true \
		-e FIX_NATURAL_LANGUAGE=true \
		-e FIX_CSS_PRETTIER=true \
		-e FIX_SHELL_SHFMT=true \
		-e FIX_PYTHON_BLACK=true \
		-e FIX_PYTHON_ISORT=true \
		-e FIX_PYTHON_RUFF=true \
		-e FIX_PYTHON_RUFF_FORMAT=true \
		-e FIX_ANSIBLE=true \
	)

check-ansible: ## Run syntax checks inside the tooling container
	$(call tooling,$(check_ansible_command))

test: ## Run ansible-test sanity and unit checks inside the tooling container
	$(call tooling,$(test_command))

ci: setup ## Run the local CI equivalent
	$(MAKE) lint-fix
	$(MAKE) check-ansible
	$(MAKE) test

e2e-up: ## Start the Lima end-to-end test VM
	$(call check_lima)
	@set -e; \
	config_file="$(CURDIR)/e2e-tests/lima-ubuntu.yml"; \
	runtime_config_file="$$(mktemp "/tmp/workstation-manager-lima-XXXXXX.yml")"; \
	sed 's|location: "."|location: "$(CURDIR)"|' "$$config_file" >"$$runtime_config_file"; \
	attempt=0; \
	if limactl list $(VM_NAME) 2>/dev/null | grep -q "$(VM_NAME)"; then \
		limactl start $(VM_NAME) || true; \
	else \
		limactl start -y --containerd=none --name=$(VM_NAME) "$$runtime_config_file" || true; \
	fi; \
	rm -f "$$runtime_config_file"; \
	until limactl shell --workdir / $(VM_NAME) true 2>/dev/null; do \
		attempt=$$((attempt + 1)); \
		if [ $$attempt -ge 60 ]; then \
			echo "e2e VM did not become reachable" >&2; \
			exit 1; \
		fi; \
	done

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
	DEFAULT_USERNAME="$(shell id -un)"; \
	LINTER_IMAGE="linter:latest"; \
	VOLUME="$$DEFAULT_WORKSPACE:$$DEFAULT_WORKSPACE"; \
	docker build --build-arg UID=$(shell id -u) --build-arg GID=$(shell id -g) --tag $$LINTER_IMAGE .; \
	docker run \
		-e DEFAULT_WORKSPACE="$$DEFAULT_WORKSPACE" \
		-e LOGNAME="$$DEFAULT_USERNAME" \
		-e ANSIBLE_CONFIG_FILE=.ansible-lint \
		-e FILTER_REGEX_INCLUDE="$(filter-out $@,$(MAKECMDGOALS))" \
		-e IGNORE_GITIGNORED_FILES=true \
		-e USER="$$DEFAULT_USERNAME" \
		-e USERNAME="$$DEFAULT_USERNAME" \
		-e VALIDATE_GIT_COMMITLINT=false \
        -e VALIDATE_TYPESCRIPT_ES=false \
        -e VALIDATE_TYPESCRIPT_PRETTIER=false \
        -e VALIDATE_JAVASCRIPT_ES=false \
        -e VALIDATE_TSX=false \
		$(1) \
		-v $$VOLUME \
		--rm \
		$$LINTER_IMAGE
endef

define tooling
	@docker run --rm \
		--user "$(HOST_UID):$(HOST_GID)" \
		--env ANSIBLE_HOME=/tmp/.ansible \
		--env HOME=/tmp \
		--env XDG_CACHE_HOME=/tmp/.cache \
		--volume "$(CURDIR):/workspace" \
		--workdir /workspace \
		"$(TOOLING_IMAGE)" \
		bash -lc '$(1)'
endef

define install_collection_requirements_command
	export ANSIBLE_COLLECTIONS_PATH="/workspace/ansible/vendor-collections:/workspace/ansible/collections"; \
	if [ -f ansible/collections/requirements.yml ]; then \
		ansible-galaxy collection install -r ansible/collections/requirements.yml -p ansible/vendor-collections >/dev/null; \
	fi
endef

define check_ansible_command
	$(install_collection_requirements_command); \
	export ANSIBLE_COLLECTIONS_PATH="/workspace/ansible/vendor-collections:/workspace/ansible/collections"; \
	if [ -n "$(REPORTS_DIR)" ]; then \
		/workspace/ci/run-with-junit.sh \
			"/workspace/$(REPORTS_DIR)/tests/check-ansible.junit.xml" \
			"ansible" \
			"syntax-check" \
			bash -lc "for playbook in $(ANSIBLE_PLAYBOOK_FILES); do ansible-playbook --syntax-check -i ansible/inventory.yml \"\$$playbook\" || exit \$$?; done"; \
	else \
		for playbook in $(ANSIBLE_PLAYBOOK_FILES); do ansible-playbook --syntax-check -i ansible/inventory.yml "$$playbook"; done; \
	fi
endef

define test_command
	set -e; \
	export ANSIBLE_COLLECTIONS_PATH="/workspace/ansible/vendor-collections:/workspace/ansible/collections"; \
	if [ -f /workspace/ansible/collections/requirements.yml ]; then \
		ansible-galaxy collection install -r /workspace/ansible/collections/requirements.yml -p /workspace/ansible/vendor-collections >/dev/null; \
	fi; \
	if [ -n "$(REPORTS_DIR)" ]; then \
		for collection_dir in $(FIRST_PARTY_COLLECTION_DIRS); do \
			collection_name="$$(basename "$$collection_dir")"; \
			/workspace/ci/run-with-junit.sh \
				"/workspace/$(REPORTS_DIR)/tests/ansible-test-sanity-$${collection_name}.junit.xml" \
				"ansible-test-$${collection_name}" \
				"sanity" \
				bash -lc "cd $$collection_dir && ansible-test sanity --python 3.12"; \
			if [ -d "$$collection_dir/tests/unit" ]; then \
				/workspace/ci/run-with-junit.sh \
					"/workspace/$(REPORTS_DIR)/tests/ansible-test-units-$${collection_name}.junit.xml" \
					"ansible-test-$${collection_name}" \
					"units" \
					bash -lc "cd $$collection_dir && ansible-test units --python 3.12"; \
			fi; \
		done; \
	else \
		for collection_dir in $(FIRST_PARTY_COLLECTION_DIRS); do \
			cd "$$collection_dir"; \
			ansible-test sanity --python 3.12; \
			if [ -d tests/unit ]; then \
				ansible-test units --python 3.12; \
			fi; \
			cd /workspace; \
		done; \
	fi
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