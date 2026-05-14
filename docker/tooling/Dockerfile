ARG TOOLING_UID=1000
ARG TOOLING_GID=1000

FROM python:3.12-slim

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
    openssh-client && \
    sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${TOOLING_GID}" tooling && \
    useradd --uid "${TOOLING_UID}" --gid "${TOOLING_GID}" --create-home --shell /bin/bash tooling && \
    mkdir -p /workspace && \
    chown tooling:tooling /workspace

COPY docker/tooling/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

HEALTHCHECK --interval=5m --timeout=10s --start-period=30s --retries=3 CMD ["python", "--version"]

WORKDIR /workspace
USER tooling
CMD ["bash"]
