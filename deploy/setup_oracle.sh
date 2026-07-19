#!/usr/bin/env bash
# ============================================================================
# Installation automatique du bot Telegram sur une VM Oracle Cloud (Ubuntu).
# À lancer UNE fois, connecté en SSH sur la machine :
#     bash setup_oracle.sh
# Il installe Python, télécharge le projet, installe les dépendances,
# demande ton token Telegram, et lance le bot en service (démarrage auto).
# ============================================================================
set -e

REPO_URL="https://github.com/paulinhoooooooooo/cycle_analyser.git"
BRANCH="claude/ecstatic-maxwell-vjoocl"
APP_DIR="$HOME/cycle_analyser"

echo "==> 1/6  Mise à jour du système et installation de Python…"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git

echo "==> 2/6  Récupération du projet…"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull origin "$BRANCH"
else
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

echo "==> 3/6  Création de l'environnement Python et des dépendances…"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> 4/6  Configuration du token Telegram…"
if [ ! -f "$APP_DIR/cyclebot.env" ]; then
    read -rp "Colle ton TOKEN Telegram (BotFather) puis Entrée : " TOKEN
    cat > "$APP_DIR/cyclebot.env" <<EOF
TELEGRAM_TOKEN=$TOKEN
# Alertes du soir gérées par GitHub Actions -> on les désactive ici (pas de doublon).
# Le bot ne fait que répondre à /prochains.
DISABLE_DAILY_ALERTS=1
EOF
    chmod 600 "$APP_DIR/cyclebot.env"
    echo "    Token enregistré dans cyclebot.env (privé)."
else
    echo "    cyclebot.env existe déjà — on le garde."
fi

echo "==> 5/6  Installation du service (démarrage automatique)…"
sudo cp "$APP_DIR/deploy/cyclebot.service" /etc/systemd/system/cyclebot.service
sudo systemctl daemon-reload
sudo systemctl enable cyclebot
sudo systemctl restart cyclebot

echo "==> 6/6  Terminé ! État du bot :"
sleep 3
sudo systemctl status cyclebot --no-pager -l | head -n 12 || true

cat <<'EOF'

============================================================================
✅  Bot installé et lancé. Envoie /prochains à ton bot dans Telegram !

Commandes utiles (à copier-coller si besoin) :
  sudo systemctl status cyclebot     # voir si le bot tourne
  sudo journalctl -u cyclebot -f     # voir les logs en direct (Ctrl+C pour sortir)
  sudo systemctl restart cyclebot    # redémarrer le bot

Pour mettre à jour le bot après un changement de code :
  cd ~/cycle_analyser && git pull && sudo systemctl restart cyclebot
============================================================================
EOF
