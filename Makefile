PY := api/.venv/bin/python
PIP := api/.venv/bin/pip

.PHONY: install share bootstrap bulk metadata daily derive derive-all events cover quotes export dev api web build test clean status regress audit audit-filings

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

derive:                        ## recompute dashboard-eligible snapshots (no refetch)
	cd api && .venv/bin/python -m screener.sync derive

derive-all:                    ## recompute every cached snapshot, including deferred filers
	cd api && .venv/bin/python -m screener.sync derive --all-snapshots

events:                        ## material 8-K items (restatements, delisting notices) per company
	cd api && .venv/bin/python -m screener.sync events

cover:                         ## read each filing's cover: which security the ticker prices
	cd api && .venv/bin/python -m screener.sync cover

quotes:                        ## refresh every universe quote using stored histories
	cd api && .venv/bin/python -m screener.sync quotes

export:                        ## write dashboard.json (adds live prices)
	cd api && .venv/bin/python -m screener.sync export

audit:                         ## check every displayed number against the filing it came from
	cd api && .venv/bin/python -m screener.audit $(ARGS)

audit-filings:                 ## ...and against the statements the company published (network)
	cd api && .venv/bin/python -m screener.audit --filings $(ARGS)

regress:                       ## diff every number against the shipped payload after an engine change
	cd api && .venv/bin/python -m screener.regress $(ARGS)

verify-coverage:               ## prove the sampled companies hide no unread material facts
	cd api && .venv/bin/python -m screener.coverage

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
