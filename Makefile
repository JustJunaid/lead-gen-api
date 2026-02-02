COMPOSE_FILE = docker-compose.prod.yml

.PHONY: deploy up down restart build logs status migrate shell

## Full deploy (build + start + migrate)
deploy:
	docker compose -f $(COMPOSE_FILE) build
	docker compose -f $(COMPOSE_FILE) up -d
	@sleep 5
	docker compose -f $(COMPOSE_FILE) exec -T api python -m alembic upgrade head
	@echo "Deployed. Run 'make status' to verify."

## Start all services
up:
	docker compose -f $(COMPOSE_FILE) up -d

## Stop all services
down:
	docker compose -f $(COMPOSE_FILE) down

## Restart all services
restart:
	docker compose -f $(COMPOSE_FILE) restart

## Rebuild images and restart
build:
	docker compose -f $(COMPOSE_FILE) build
	docker compose -f $(COMPOSE_FILE) up -d

## Tail logs (all services)
logs:
	docker compose -f $(COMPOSE_FILE) logs -f --tail=100

## Show running containers
status:
	docker compose -f $(COMPOSE_FILE) ps

## Run database migrations
migrate:
	docker compose -f $(COMPOSE_FILE) exec -T api python -m alembic upgrade head

## Open a shell in the API container
shell:
	docker compose -f $(COMPOSE_FILE) exec api bash
