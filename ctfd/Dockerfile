ARG CTFD_BASE_IMAGE=ctfd/ctfd:latest
FROM ${CTFD_BASE_IMAGE}

RUN pip install --no-cache-dir httpx==0.27.0

# First-party bundled distribution: bake the IsolateX plugin into the CTFd image.
# This keeps bundled mode working even without bind-mounted plugin files.
COPY ctfd-plugin /opt/CTFd/CTFd/plugins/isolatex
