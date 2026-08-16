PY := api/.venv/bin/python
PIP := api/.venv/bin/pip

.PHONY: install share bootstrap bulk metadata daily derive export dev api web build test clean status

install:                       ## set up both workspaces
	python3 -m venv api/.venv
	$(PIP) install -q -r api/requirements.txt
	cd web && npm install

bootstrap:                     ## derive snapshots from raw facts already cached (no network)
	cd api && .venv/bin/python -m screener.sync bootstrap

bulk:                          ## first full load: one 1.4GB download instead of 4,000 requests
	cd api && .venv/bin/python -m screener.sync bulk

metadata:                      ## sector + exchange from SEC's submissions archive
	cd api && .venv/bin/python -m screener.sync metadata

daily:                         ## catch up: refetch only companies that filed since last sync
	cd api && .venv/bin/python -m screener.sync daily

derive:                        ## recompute snapshots after an engine change (no refetch)
	cd api && .venv/bin/python -m screener.sync derive

export:                        ## write dashboard.json (adds live prices)
	cd api && .venv/bin/python -m screener.sync export

status:
	cd api && .venv/bin/python -m screener.sync status

api:                           ## API only, port 8000
	cd api && .venv/bin/uvicorn screener.api:app --reload

web:                           ## Vite dev server, proxies to the API
	cd web && npm run dev

build:                         ## build the SPA into the API package
	cd web && npm run build

share:                         ## expose the dashboard through an ngrok tunnel
	./share.sh

dev:                           ## everything: API + Vite together
	$(MAKE) -j2 api web

test:                          ## python + web tests
	cd api && .venv/bin/pytest -q
	cd web && npm test --silent

clean:
	rm -rf api/screener/static/ui web/node_modules web/dist
