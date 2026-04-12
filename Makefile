.PHONY: dev desktop-dev-services dev-frontend dev-frontend-desktop dev-backend build install clean

# Development
dev:
	@echo "Starting Hermes Studio..."
	@make -j2 dev-frontend dev-backend

dev-frontend:
	cd frontend && npm run dev

dev-frontend-desktop:
	cd frontend && VITE_PORT=1420 npm run dev

dev-backend:
	cd backend && python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8420

desktop-dev-services:
	./scripts/desktop-dev-services.sh

# Production build
build:
	cd frontend && npm run build
	rm -rf backend/static
	cp -r frontend/dist backend/static

# Install dependencies
install:
	cd frontend && npm install
	cd backend && uv sync

# Clean
clean:
	rm -rf frontend/node_modules frontend/dist backend/static backend/.venv
