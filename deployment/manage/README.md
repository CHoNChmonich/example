# Директория управления стендом

1) **start.sh** — сборка образов и запуск контейнеров (флаг `--dev` опционален). В режиме
   разработки compose работает в foreground и пишет логи всех контейнеров в консоль (Ctrl+C
   останавливает стенд), в production — в фоне.
2) **restart.sh** — перезапуск с пересборкой образов (`down` + `up --build`).
3) **stop.sh** — остановка контейнеров без удаления.
4) **remove.sh** — удаление контейнеров, сети и собранных образов. Volumes с данными Postgres
   и pgAdmin остаются; удалить вместе с ними:
   из `deployment/`: `docker compose -f docker-composes/dev/docker-compose.dev.yml down -v`
   (для production — `docker-composes/prod/docker-compose.prod.yml`).

Флаг `--dev` управляет контейнерами разработки (`docker-composes/dev/docker-compose.dev.yml`,
проект `orders-service-dev`). Для production версии команды вызываются без флага
(`docker-composes/prod/docker-compose.prod.yml`, проект `orders-service`).

Скрипты экспортируют переменные корневого `.env` и запускаются из любого каталога;
на Windows — из Git Bash.

## КОМАНДЫ:

```commandline
bash start.sh --dev
```

```commandline
bash restart.sh --dev
```

```commandline
bash stop.sh --dev
```

```commandline
bash remove.sh --dev
```
