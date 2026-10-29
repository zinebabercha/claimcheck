.PHONY: install dev-api dev-web test eval eval-retrieval docker demo-pdf

install:
	pip install -r backend/requirements-dev.txt
	cd frontend && npm install

dev-api:
	cd backend && uvicorn claimcheck.api:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest -q

eval:
	python eval/run_eval.py

eval-retrieval:
	python eval/run_eval.py --retrieval-only

demo-pdf:
	python scripts/make_demo_pdf.py

docker:
	docker build -t claimcheck . && docker run --rm -p 7860:7860 --env-file .env claimcheck
