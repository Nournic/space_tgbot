#!/usr/bin/env sh
# Деплой текущего коммита (HEAD) на VPS и перезапуск контейнера.
# Использование: ./deploy.sh [ssh-хост] [папка-на-сервере]
# Незакоммиченные изменения в архив НЕ попадают. .env на сервере не трогается.
set -eu

HOST="${1:-vps_server}"
DIR="${2:-space_tgbot}"

git archive --format=tar.gz -o bot.tgz HEAD
trap 'rm -f bot.tgz' EXIT
scp bot.tgz "$HOST:~/bot.tgz"
ssh "$HOST" "mkdir -p ~/$DIR && tar -xzf ~/bot.tgz -C ~/$DIR && rm ~/bot.tgz && cd ~/$DIR && docker compose up -d --build"
echo "Готово: $HOST:~/$DIR"
