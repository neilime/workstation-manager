ARG TOOLING_UID=1000
ARG TOOLING_GID=1000

FROM ubuntu:26.04

ARG TOOLING_UID
ARG TOOLING_GID

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
    git \
    locales \
    openssh-client \
    procps \
    python3 \
    python3-venv \
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
COPY e2e-tests/requirements.txt /opt/e2e-tests/requirements.txt
RUN . /etc/os-release && test "$VERSION_ID" = "$(cat /opt/ansible/ubuntu-version)" && \
    python3 -m venv /opt/tooling/venv && \
    pip install --no-cache-dir \
    -r /opt/docker/tooling/requirements.txt \
    -r /opt/e2e-tests/requirements.txt

COPY ansible/collections/requirements.yml /opt/ansible/requirements.yml
RUN ansible-galaxy collection install -r /opt/ansible/requirements.yml -p /opt/ansible/collections

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 CMD ["python", "--version"]

WORKDIR /workspace
USER tooling
CMD ["bash"]
