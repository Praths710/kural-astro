#!/usr/bin/env bash
# One-time setup of Kural Astro on an Oracle Cloud Always Free Ubuntu server.
#   curl -fsSL https://raw.githubusercontent.com/Praths710/kural-astro/main/deploy/oracle/setup.sh -o setup.sh && bash setup.sh
# It installs Docker, opens ports 80 and 443 in the server's own firewall, downloads the app, asks for the secrets
# (typed here on the server, never stored anywhere else), starts the app behind HTTPS and turns on auto-deploy.
set -euo pipefail
REPO=https://github.com/Praths710/kural-astro.git
DIR="$HOME/kural-astro"

echo "== 1/6 Docker"
if ! command -v docker > /dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER" || true
DOCKER="sudo docker"

echo "== 2/6 Firewall: allow web traffic (Oracle's Ubuntu images block it by default)"
for p in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2> /dev/null || sudo iptables -I INPUT 1 -p tcp --dport "$p" -j ACCEPT
done
sudo apt-get update -q > /dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q iptables-persistent > /dev/null || true
sudo netfilter-persistent save > /dev/null 2>&1 || true

echo "== 3/6 Download the app"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q; else git clone -q "$REPO" "$DIR"; fi
cd "$DIR"

echo "== 4/6 Secrets (typed here, saved only in $DIR/.env on this server)"
if [ ! -f .env ]; then
  IP=$(curl -fsS https://api.ipify.org)
  read -rsp "GEMINI_API_KEY: " GEMINI; echo
  read -rsp "DATABASE_URL (the Neon address): " DBURL; echo
  read -rp  "INVITE_CODE: " INVITE
  umask 077
  cat > .env <<EOF
GEMINI_API_KEY=$GEMINI
DATABASE_URL=$DBURL
INVITE_CODE=$INVITE
SECRET_KEY=$(openssl rand -hex 32)
SITE_HOST=kural-astro.${IP//./-}.sslip.io
EOF
fi
SITE_HOST=$(grep '^SITE_HOST=' .env | cut -d= -f2)

echo "== 5/6 Build and start (first build takes a few minutes)"
$DOCKER compose -f deploy/oracle/docker-compose.yml up -d --build

echo "== 6/6 Auto-deploy: check GitHub every 5 minutes"
chmod +x deploy/oracle/update.sh
( crontab -l 2> /dev/null | grep -v kural-astro/deploy/oracle/update.sh;
  echo "*/5 * * * * $DIR/deploy/oracle/update.sh >> $DIR/deploy.log 2>&1" ) | crontab -

echo
echo "Done. In a minute or two the site will be live at:  https://$SITE_HOST"
echo "If it does not open, check that ports 80 and 443 are open in the Oracle subnet's security list."
