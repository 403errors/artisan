# execution-sandbox Cloud Run Job image (MILESTONE.md Phase 3.4). Multi-stage, uv-based build,
# mirroring agents/Dockerfile's shape (see that file's comments for why the build context must be
# the repo root, not execution-sandbox/, given the uv workspace path dependency on
# packages/artisan_shared):
#   docker build -f execution-sandbox/Dockerfile -t execution-sandbox .   (run from the repo root)
#   gcloud run jobs deploy execution-sandbox --image <pushed-image-tag> --region us-central1
#
# Needs `git` in the final image (unlike agents/, which only talks to GitHub over the REST API) —
# this job shells out to the real `git` CLI to clone/branch/commit/push (see git_ops.py).
#
# Polyglot toolchain (v2 exec-env generalization): one image carries every ecosystem's toolchain —
# Node, Python+uv, Go, Rust, JDK+Maven+Gradle — so any repo's resolved install/build/test commands
# (repo_config.py) can actually run, and the coding agent's allowlisted shell checks work in any
# language. Deliberate tradeoff vs per-language images: ~3-4 GB image and a slower cold start in
# exchange for one job template and sandbox-side (post-clone) ecosystem resolution. This also
# fixes a latent v1 gap: the image previously had NO Node despite `npm test` being the default
# test command. All toolchains install for both amd64 (Cloud Run) and arm64 (local Apple Silicon
# builds): the arch comes from TARGETARCH when BuildKit provides it, else from `uname -m` (the
# base image's real arch — the legacy builder leaves TARGETARCH empty). Versions are pinned except
# the JDK (Adoptium's "latest 21 GA" endpoint — no stable per-version URL; floats within 21 LTS).

FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY execution-sandbox/pyproject.toml execution-sandbox/pyproject.toml
COPY packages/artisan_shared/pyproject.toml packages/artisan_shared/pyproject.toml
COPY packages/artisan_shared/src packages/artisan_shared/src
RUN uv sync --frozen --no-install-project --no-dev --package artisan-execution-sandbox

COPY execution-sandbox/src execution-sandbox/src
RUN uv sync --frozen --no-dev --package artisan-execution-sandbox

FROM python:3.13-slim
# uv is needed at RUNTIME (not just build): repo_config's Python detection installs target-repo
# deps via `uv pip install --system` mid-job.
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/
ARG TARGETARCH
ARG NODE_VERSION=22.17.0
ARG GO_VERSION=1.24.5
ARG RUST_VERSION=1.88.0
ARG MAVEN_VERSION=3.9.9
ARG GRADLE_VERSION=8.14

# git/curl: clone+push and toolchain downloads. make/gcc/g++: native builds (node-gyp, pip
# source wheels, cargo crates with C deps). unzip: the Gradle distribution.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl make gcc g++ unzip \
    && rm -rf /var/lib/apt/lists/*

# Node LTS + pnpm/yarn via corepack. `corepack prepare --activate` pre-downloads pinned versions
# at BUILD time — plain `corepack enable` only installs shims, so first use would download the
# package manager at runtime (a flaky network dependency inside a job container; caught in the
# build smoke). Repos pinning `packageManager` in package.json still get their exact version.
# Arch detection: TARGETARCH comes from BuildKit only — the legacy builder (and some Cloud Build
# configs) leave it empty, so fall back to `uname -m`, which always matches the pulled base
# image's real architecture (aarch64 on Apple Silicon, x86_64 on Cloud Build).
RUN ARCH="${TARGETARCH:-$(uname -m)}" && case "$ARCH" in aarch64|arm64) NODE_ARCH=arm64 ;; *) NODE_ARCH=x64 ;; esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz" -o /tmp/node.tar.gz \
    && tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.gz \
    && corepack enable \
    && corepack prepare pnpm@9.15.0 --activate \
    && corepack prepare yarn@4.5.1 --activate

# Go.
RUN ARCH="${TARGETARCH:-$(uname -m)}" && case "$ARCH" in aarch64|arm64) GO_ARCH=arm64 ;; *) GO_ARCH=amd64 ;; esac \
    && curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" -o /tmp/go.tar.gz \
    && tar -C /usr/local -xzf /tmp/go.tar.gz \
    && rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:$PATH"

# Rust (rustup, minimal profile) into system-wide CARGO_HOME/RUSTUP_HOME.
ENV CARGO_HOME=/usr/local/cargo RUSTUP_HOME=/usr/local/rustup
RUN ARCH="${TARGETARCH:-$(uname -m)}" && case "$ARCH" in aarch64|arm64) RUST_ARCH=aarch64 ;; *) RUST_ARCH=x86_64 ;; esac \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --profile minimal --default-toolchain ${RUST_VERSION}-${RUST_ARCH}-unknown-linux-gnu \
    && rm -rf /usr/local/cargo/registry
ENV PATH="/usr/local/cargo/bin:$PATH"

# Temurin JDK 21 + Maven + Gradle.
RUN ARCH="${TARGETARCH:-$(uname -m)}" && case "$ARCH" in aarch64|arm64) JDK_ARCH=aarch64 ;; *) JDK_ARCH=x64 ;; esac \
    && curl -fsSL "https://api.adoptium.net/v3/binary/latest/21/ga/linux/${JDK_ARCH}/jdk/hotspot/normal/eclipse" -o /tmp/jdk.tar.gz \
    && mkdir -p /usr/local/jdk \
    && tar -xzf /tmp/jdk.tar.gz -C /usr/local/jdk --strip-components=1 \
    && rm /tmp/jdk.tar.gz \
    && curl -fsSL "https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" -o /tmp/maven.tar.gz \
    && tar -xzf /tmp/maven.tar.gz -C /usr/local \
    && rm /tmp/maven.tar.gz \
    && curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -o /tmp/gradle.zip \
    && unzip -q -d /usr/local /tmp/gradle.zip \
    && rm /tmp/gradle.zip
ENV JAVA_HOME=/usr/local/jdk
ENV PATH="/usr/local/jdk/bin:/usr/local/apache-maven-${MAVEN_VERSION}/bin:/usr/local/gradle-${GRADLE_VERSION}/bin:$PATH"

# Pre-push secrets scan (Workstream 6, security_scan.py's scan_secrets) — a specific pinned
# gitleaks release binary, installed straight from its GitHub release tarball rather than an apt
# package (Debian doesn't ship one).
RUN curl -sSL -o /tmp/gitleaks.tar.gz \
        https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm /tmp/gitleaks.tar.gz

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["artisan-execution-sandbox"]
