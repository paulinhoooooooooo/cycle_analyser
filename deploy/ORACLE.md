# Héberger le bot `/prochains` GRATUITEMENT sur Oracle Cloud (Always Free)

Ce guide met ton bot Telegram sur une petite machine gratuite **à vie**, allumée
24h/24, pour que `/prochains` réponde dans le chat comme avant — sans Railway.

> Les **alertes du soir** restent gérées gratuitement par GitHub Actions.
> Ce bot Oracle ne sert QU'À répondre à `/prochains` (les alertes du bot sont
> désactivées automatiquement pour éviter les doublons).

---

## Phase 1 — Créer le compte et la machine (~15 min)

1. Va sur **https://www.oracle.com/cloud/free/** → **Start for free**.
2. Crée le compte (email, pays = France). Une **carte bancaire** est demandée
   pour vérifier l'identité : sur l'offre **Always Free**, elle **n'est jamais
   débitée**. Choisis une région proche (ex : *Paris* ou *Frankfurt*).
3. Une fois connecté à la console Oracle : menu ☰ → **Compute** → **Instances**
   → **Create instance**.
4. Réglages :
   - **Name** : `cyclebot` (peu importe).
   - **Image and shape** → **Edit** → **Image** : choisis **Canonical Ubuntu**
     (22.04). **Shape** : garde une forme marquée **« Always Free-eligible »**
     (ex : *VM.Standard.E2.1.Micro*). Si tu vois *Ampere/A1* aussi Always-Free,
     c'est encore mieux, mais l'E2.1.Micro suffit largement.
   - **Add SSH keys** : laisse **Generate a key pair for me** →
     **Save private key** (⚠️ télécharge et garde bien ce fichier `.key`, il te
     servira à te connecter). **Save public key** aussi.
5. Clique **Create**. Attends que l'état passe à **RUNNING**, puis note
   l'**adresse IP publique** affichée (ex : `123.45.67.89`).

---

## Phase 2 — Se connecter à la machine (SSH)

### Sur Windows (PowerShell — intégré)
1. Mets le fichier `.key` téléchargé dans un dossier simple, ex : `C:\Users\toi\`.
2. Ouvre **PowerShell** et tape (remplace le chemin et l'IP) :
   ```powershell
   ssh -i C:\Users\toi\ta-cle.key ubuntu@123.45.67.89
   ```
3. Tape `yes` à la question de confiance. Tu es connecté quand l'invite devient
   `ubuntu@cyclebot:~$`.

> Erreur « permissions too open » ? Fais un clic droit sur le fichier `.key` →
> Propriétés → Sécurité → n'autorise que ton utilisateur. (Sur Mac/Linux :
> `chmod 600 ta-cle.key`.)

### Sur Mac
Ouvre **Terminal** :
```bash
chmod 600 ~/Downloads/ta-cle.key
ssh -i ~/Downloads/ta-cle.key ubuntu@123.45.67.89
```

---

## Phase 3 — Installer le bot (1 seule commande)

> **Prérequis** : le dépôt doit être téléchargeable par la machine.
> Le plus simple : sur GitHub, **Settings → General → Danger Zone →
> Change visibility → Public** (aucun secret n'est dans le code, c'est sûr).
> _(Tu préfères le garder privé ? voir la note en bas.)_

Une fois connecté en SSH, copie-colle **ces deux lignes** :

```bash
curl -fsSL https://raw.githubusercontent.com/paulinhoooooooooo/cycle_analyser/claude/ecstatic-maxwell-vjoocl/deploy/setup_oracle.sh -o setup_oracle.sh
bash setup_oracle.sh
```

Le script installe tout, te demande de **coller ton token Telegram** (celui de
BotFather), puis lance le bot en service. À la fin il affiche « Bot installé ».

**Teste : envoie `/prochains` à ton bot dans Telegram → il doit répondre. 🎉**

---

## Vérifier / dépanner

```bash
sudo systemctl status cyclebot     # le bot tourne-t-il ?
sudo journalctl -u cyclebot -f     # logs en direct (Ctrl+C pour sortir)
sudo systemctl restart cyclebot    # redémarrer
```

Le bot redémarre tout seul en cas de plantage **et après un reboot** de la
machine — rien à refaire.

## Mettre à jour le bot plus tard
```bash
cd ~/cycle_analyser && git pull && sudo systemctl restart cyclebot
```

---

## (Optionnel) Garder le dépôt PRIVÉ

Si tu ne veux pas rendre le repo public, crée un **jeton d'accès GitHub** :
GitHub → **Settings** (ton profil) → **Developer settings** → **Personal access
tokens** → **Fine-grained tokens** → **Generate** (accès *lecture* au repo).
Puis, dans la commande de clonage, utilise l'URL avec le jeton :
`https://<TON_JETON>@github.com/paulinhoooooooooo/cycle_analyser.git`.
Dis-le-moi et je t'adapte le script.
