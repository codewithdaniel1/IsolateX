#!/usr/bin/env bash
# Build a Firecracker-compatible kernel + rootfs for a challenge.
#
# Usage:
#   ./build-image.sh <challenge-dir> <output-dir>
#
# <challenge-dir> must contain:
#   Dockerfile        — your challenge app
#   challenge.yaml    — runtime config (see infra/firecracker/challenge.yaml.example)
#
# Output:
#   <output-dir>/vmlinux       — Linux kernel image
#   <output-dir>/rootfs.ext4  — challenge rootfs
#
# Requirements:
#   docker, e2tools or mke2fs, curl
set -euo pipefail

CHALLENGE_DIR="${1:?Usage: $0 <challenge-dir> <output-dir>}"
OUTPUT_DIR="${2:?Usage: $0 <challenge-dir> <output-dir>}"
KERNEL_VERSION="${FC_KERNEL_VERSION:-5.10.225}"
KERNEL_URL="https://s3.amazonaws.com/spec.ccfc.min/firecracker-ci/v1.9/x86_64/vmlinux-${KERNEL_VERSION}"

mkdir -p "$OUTPUT_DIR"

echo "[build-image] Building challenge image from $CHALLENGE_DIR"

# ── 1. Download kernel ────────────────────────────────────────────────────────
KERNEL_OUT="$OUTPUT_DIR/vmlinux"
if [[ ! -f "$KERNEL_OUT" ]]; then
    echo "[build-image] Downloading kernel vmlinux-${KERNEL_VERSION}..."
    curl -fsSL -o "$KERNEL_OUT" "$KERNEL_URL"
else
    echo "[build-image] Kernel already present, skipping download"
fi

# ── 2. Build challenge Docker image ──────────────────────────────────────────
TAG="isolatex-challenge-build:$(basename "$CHALLENGE_DIR")"
echo "[build-image] Building Docker image $TAG..."
docker build -t "$TAG" "$CHALLENGE_DIR"

# ── 3. Export Docker image to rootfs ext4 ────────────────────────────────────
ROOTFS_SIZE="${FC_ROOTFS_SIZE_MB:-512}"
ROOTFS_OUT="$OUTPUT_DIR/rootfs.ext4"
TMPDIR_FS=$(mktemp -d)

echo "[build-image] Exporting filesystem (${ROOTFS_SIZE}MB)..."
CID=$(docker create "$TAG")
docker export "$CID" | tar -xf - -C "$TMPDIR_FS"
docker rm "$CID"

echo "[build-image] Creating ext4 rootfs..."
dd if=/dev/zero of="$ROOTFS_OUT" bs=1M count="$ROOTFS_SIZE" status=none
mkfs.ext4 -F -L rootfs "$ROOTFS_OUT" >/dev/null

MNTDIR=$(mktemp -d)
mount -o loop "$ROOTFS_OUT" "$MNTDIR"
cp -a "$TMPDIR_FS/." "$MNTDIR/"
umount "$MNTDIR"

rm -rf "$TMPDIR_FS" "$MNTDIR"
echo "[build-image] Done."
echo "  Kernel:  $KERNEL_OUT"
echo "  Rootfs:  $ROOTFS_OUT (${ROOTFS_SIZE}MB)"
echo ""
echo "Register this challenge with the orchestrator:"
echo "  curl -X POST http://orchestrator:8080/challenges \\"
echo "    -H 'x-api-key: \$API_KEY' \\"
echo "    -H 'content-type: application/json' \\"
echo "    -d '{"
echo "      \"id\": \"$(basename "$CHALLENGE_DIR")\","
echo "      \"name\": \"$(basename "$CHALLENGE_DIR")\","
echo "      \"runtime\": \"firecracker\","
echo "      \"kernel_image\": \"$KERNEL_OUT\","
echo "      \"rootfs_image\": \"$ROOTFS_OUT\","
echo "      \"port\": 8888"
echo "    }'"
