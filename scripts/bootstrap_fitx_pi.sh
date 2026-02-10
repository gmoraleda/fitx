#!/usr/bin/env bash
set -euo pipefail

# Bootstrap and control script for FitX ICS on Raspberry Pi (armv7, no systemd)
# - Mounts cgroups
# - Starts dockerd with a custom data-root
# - Brings up the compose stack (fitx-calendar + cloudflared)
# - Optionally installs rc.local boot hooks

PROJECT_DIR="${PROJECT_DIR:-$HOME/fitx-calendar}"
DATA_ROOT="${DATA_ROOT:-$HOME/docker-data}"
DOCKER_BIN="${DOCKER_BIN:-/usr/bin/docker}"
DOCKERD_BIN="${DOCKERD_BIN:-/usr/bin/dockerd}"
RC_LOCAL="/etc/rc.local"
COMPOSE_FILES=("-f" "docker-compose.armv7.yml" "-f" "docker-compose.armv7.cloudflared.yml")

log() { printf "[%s] %s\n" "$(date +'%F %T')" "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }; }

mount_cgroups() {
  log "Mounting cgroup controllers (v1)"
  if command -v cgroupfs-mount >/dev/null 2>&1; then
    sudo cgroupfs-mount || true
    return
  fi
  sudo mkdir -p /sys/fs/cgroup
  # Mount all enabled controllers
  while read -r ctl; do
    [ -z "$ctl" ] && continue
    sudo mkdir -p "/sys/fs/cgroup/$ctl"
    if ! mountpoint -q "/sys/fs/cgroup/$ctl"; then
      sudo mount -t cgroup -o "$ctl" cgroup "/sys/fs/cgroup/$ctl" || true
    fi
  done < <(awk 'NR>1 && $4==1 {print $1}' /proc/cgroups)
  # Ensure devices specifically
  sudo mkdir -p /sys/fs/cgroup/devices
  mountpoint -q /sys/fs/cgroup/devices || sudo mount -t cgroup -o devices cgroup /sys/fs/cgroup/devices || true
}

start_dockerd() {
  log "Ensuring Docker daemon running with data-root: $DATA_ROOT"
  sudo mkdir -p "$DATA_ROOT"
  if pgrep -x dockerd >/dev/null 2>&1; then
    log "dockerd already running"
    return 0
  fi
  sudo nohup "$DOCKERD_BIN" --data-root="$DATA_ROOT" -H unix:///var/run/docker.sock >>/var/log/dockerd.log 2>&1 &
  # Wait for socket
  for i in {1..15}; do
    if [ -S /var/run/docker.sock ]; then
      break
    fi
    sleep 1
  done
  if [ ! -S /var/run/docker.sock ]; then
    log "Docker socket not available; recent dockerd log:"
    sudo tail -n 80 /var/log/dockerd.log || true
    exit 1
  fi
}

compose() {
  ( cd "$PROJECT_DIR" && "$DOCKER_BIN" compose "${COMPOSE_FILES[@]}" "$@" )
}

up() {
  need_cmd "$DOCKER_BIN"
  mount_cgroups
  start_dockerd
  log "Pulling latest images (cloudflared only)"
  compose pull cloudflared || true
  log "Bringing stack up (build if needed)"
  compose up -d --build
  status
}

down() {
  need_cmd "$DOCKER_BIN"
  log "Stopping stack"
  compose down || true
}

status() {
  need_cmd "$DOCKER_BIN"
  log "Docker ps:"; "$DOCKER_BIN" ps || true
  log "Compose ps:"; compose ps || true
  if curl -fsS http://localhost:8787/health >/dev/null 2>&1; then
    log "Health: OK";
  else
    log "Health: UNREACHABLE"
  fi
}

logs() {
  need_cmd "$DOCKER_BIN"
  compose logs --tail=200 -f fitx-calendar cloudflared
}

install_boot() {
  log "Installing /etc/rc.local boot hook"
  sudo tee "$RC_LOCAL" >/dev/null <<'RC'
#!/bin/sh -e
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Mount cgroup v1 controllers
[ -d /sys/fs/cgroup ] || mkdir -p /sys/fs/cgroup
awk 'NR>1 && $4==1 {print $1}' /proc/cgroups | while read ctl; do
  d="/sys/fs/cgroup/$ctl"; [ -d "$d" ] || mkdir -p "$d"
  mountpoint -q "$d" || mount -t cgroup -o "$ctl" cgroup "$d" || true
done
mkdir -p /sys/fs/cgroup/devices
mountpoint -q /sys/fs/cgroup/devices || mount -t cgroup -o devices cgroup /sys/fs/cgroup/devices || true

# Start Docker daemon (custom data-root)
if ! pgrep -x dockerd >/dev/null; then
  /usr/bin/dockerd --data-root=/home/pi/docker-data -H unix:///var/run/docker.sock >/var/log/dockerd.log 2>&1 &
  sleep 4
fi

# Start compose stack (uses .env with TUNNEL_TOKEN etc.)
su - pi -c 'cd /home/pi/fitx-calendar && /usr/bin/docker compose -f docker-compose.armv7.yml -f docker-compose.armv7.cloudflared.yml pull cloudflared || true; /usr/bin/docker compose -f docker-compose.armv7.yml -f docker-compose.armv7.cloudflared.yml up -d' || true

exit 0
RC
  sudo chmod +x "$RC_LOCAL"
  log "Installed $RC_LOCAL. It will run at boot."
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") <command>

Commands:
  up             Mount cgroups, start dockerd, pull images, compose up -d --build
  down           Compose down
  status         Show docker and compose status + health
  logs           Tail logs for fitx-calendar and cloudflared
  install-boot   Install rc.local to auto-start on boot

Environment overrides:
  PROJECT_DIR (default: $HOME/fitx-calendar)
  DATA_ROOT   (default: $HOME/docker-data)
USAGE
}

cmd="${1:-}"
case "$cmd" in
  up) up ;;
  down) down ;;
  status) status ;;
  logs) logs ;;
  install-boot) install_boot ;;
  *) usage; exit 1 ;;
esac
