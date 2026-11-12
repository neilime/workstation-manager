ARG TOOLING_UID=1000
ARG TOOLING_GID=1000
ARG TOOLING_BASE_DIGEST

FROM ubuntu:26.04${TOOLING_BASE_DIGEST}

ARG TOOLING_UID
ARG TOOLING_GID
# CI advances this weekly so cached apt/pip layers cannot freeze floating dependencies.
ARG TOOLING_REFRESH=local

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash \
    dbus-daemon \
    curl \
    git \
    libglib2.0-bin \
    locales \
    make \
    openssh-client \
    procps \
    python3 \
    python3-gi \
    python3-venv \
    systemd \
    sudo-rs && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    rm -rf /var/lib/apt/lists/*

RUN if id ubuntu >/dev/null 2>&1; then userdel --remove ubuntu; fi && \
    groupadd --gid "${TOOLING_GID}" tooling && \
    useradd --uid "${TOOLING_UID}" --gid "${TOOLING_GID}" --create-home --shell /bin/bash tooling && \
    mkdir -p /workspace && \
    chown tooling:tooling /workspace

ENV PATH="/opt/tooling/venv/bin:${PATH}"
COPY ansible/requirements.txt /opt/ansible/requirements.txt
COPY ansible/ubuntu-version /opt/ansible/ubuntu-version
COPY docker/tooling/requirements.txt /opt/docker/tooling/requirements.txt
RUN . /etc/os-release && test "$VERSION_ID" = "$(cat /opt/ansible/ubuntu-version)" && \
    python3 -m venv /opt/tooling/venv && \
    pip install --no-cache-dir \
    -r /opt/docker/tooling/requirements.txt

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
COPY e2e-tests/goss.json /opt/goss.json
RUN version="$(python3 -c 'import json; print(json.load(open("/opt/goss.json"))["version"])')" && \
    digest="$(python3 -c 'import json; print(json.load(open("/opt/goss.json"))["sha256"])')" && \
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    "https://github.com/goss-org/goss/releases/download/v${version}/goss_${version}_linux_x86_64.tar.gz" -o /tmp/goss.tar.gz && \
    printf '%s  /tmp/goss.tar.gz\n' "$digest" | sha256sum --check --status && \
    tar -xzf /tmp/goss.tar.gz -C /usr/local/bin goss && \
    chmod 0755 /usr/local/bin/goss && rm /tmp/goss.tar.gz

COPY ansible/collections/requirements.yml /opt/ansible/requirements.yml
RUN ansible-galaxy collection install -r /opt/ansible/requirements.yml -p /opt/ansible/collections

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 CMD ["python", "--version"]

WORKDIR /workspace
USER ${TOOLING_UID}:${TOOLING_GID}
CMD ["bash"]
