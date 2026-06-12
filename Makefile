.PHONY: setup run serve web clean test help

MODEL_NAME = translator
BASE_MODEL = gemma3:1b

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Pull base model and create translator model
	ollama pull $(BASE_MODEL)
	ollama create $(MODEL_NAME) -f Modelfile

run: ## Translate text: make run TARGET=ja TEXT="Hello"
	@./translate.sh $(TARGET) "$(TEXT)"

serve: ## Start the API server
	python translate_api.py

web: serve ## Start API server (web UI at web/index.html)

docker-up: ## Start all services with Docker Compose
	docker compose up -d

docker-down: ## Stop all Docker services
	docker compose down

docker-setup: ## Docker: pull model and create translator
	docker compose up setup

batch: ## Batch translate: make batch INPUT=doc.txt TARGET=ja WORKERS=8
	python batch_pipeline.py $(INPUT) --target $(TARGET) --workers $(or $(WORKERS),8)

batch-dir: ## Batch translate dir: make batch-dir INPUT=docs/ TARGET=ja OUTPUT=out/
	python batch_pipeline.py $(INPUT) --target $(TARGET) --output $(or $(OUTPUT),translated/) --workers $(or $(WORKERS),8)

test: ## Quick smoke test
	@echo "==> Testing CLI..."
	@./translate.sh ja "Hello" && echo ""
	@echo "==> Testing API..."
	@curl -sf -X POST http://localhost:8000/translate \
		-H "Content-Type: application/json" \
		-d '{"text":"Hello","target":"ja"}' | python -m json.tool
	@echo "\n==> Health check..."
	@curl -sf http://localhost:8000/health | python -m json.tool

clean: ## Remove the translator model
	ollama rm $(MODEL_NAME)
