.PHONY: setup dev serve test lint clean

# One-command setup
setup:
	./setup.sh

# Run both backend + frontend for development
dev:
	@echo "Starting Suchi dev servers..."
	@cd backend && python -m uvicorn suchi.api:app --host 127.0.0.1 --port 9876 --reload &
	@cd frontend && npm run dev -- --host &
	@echo ""
	@echo "  Backend:  http://127.0.0.1:9876"
	@echo "  Frontend: http://localhost:5173"
	@echo ""
	@wait

# Run backend API only (CLI + API, no UI)
serve:
	cd backend && python -m uvicorn suchi.api:app --host 127.0.0.1 --port 9876

# Run tests
test:
	cd backend && python -m pytest tests/ -v

# Lint
lint:
	cd backend && ruff check src/suchi/
	cd frontend && npx tsc --noEmit

# Build frontend for production
build-frontend:
	cd frontend && npm run build

# Clean
clean:
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist backend/dist
