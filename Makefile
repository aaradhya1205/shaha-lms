.PHONY: run reset seed test big-csv

run:            ## set up (if needed) and start on :8000
	./run.sh

reset:          ## wipe + reseed demo data, then start
	./run.sh --reset

seed:           ## wipe + reseed demo data only
	.venv/bin/python -m app.seed

test:           ## run the test suite
	.venv/bin/python -m pytest -q

big-csv:        ## generate a 1,00,000-row CSV for the upload test
	.venv/bin/python scripts/generate_accounts.py --rows 100000 --out data/accounts_100000.csv
