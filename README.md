# Non-food Regulatory Monitor

Checkt Nederlandse, Belgische en EU-bronnen op relevante regelgevingswijzigingen
voor non-food (EU/NL/BE). Rebuild van een intern Précon-tool, gebaseerd op de
kolonel's echte bronbestanden (`regulatory_monitor.py`, `app.py`,
`experimental_monitor.py`, plus haar eigen `regulatory_results.csv` output) —
niet langer op gedecompileerde bytecode. `config/nonfood_monitor_config.json`
blijft de spec voor topics/keywords/exclusieregels/bronnen.

## Gebruik

```bash
pip install -r requirements.txt

# Dagelijkse + wekelijkse check (default: gisteren + huidige week)
python -m regulatory_monitor.cli

# Eén specifieke dag
python -m regulatory_monitor.cli --mode daily --from 2026-08-14

# Specifieke week
python -m regulatory_monitor.cli --mode weekly --week 16 --year 2026

# Inclusief experimentele bronnen (CEN/CENELEC, FOD Economie, RVO, SCCS, EUON, EFSA)
python -m regulatory_monitor.cli --experimental
```

Voor de dashboard-versie (twee tabs: dagelijks / wekelijks):

```bash
streamlit run app.py
```

## Gepubliceerde site (GitHub Pages)

De rapportages staan online — geen dashboard, geen knoppen, alleen de link:
**https://kmhlammers.github.io/regulatory-monitor/**

- `.github/workflows/daily.yml` draait ma–vr om ~07:15 (Amsterdam) een dagelijkse
  check en publiceert opnieuw. Zonder `--date` pakt hij automatisch alles sinds
  de vorige run t/m gisteren (max. 7 dagen), dus de maandagrun vult vr/za/zo aan.
- `.github/workflows/weekly.yml` draait maandag om ~08:15 de weekrapportage over
  de vorige ISO-week.
- Beide draaien `build_site.py`, dat elke run als JSON in `data/{daily,weekly}/`
  wegschrijft (teruggecommit naar de repo) en daarna de `public/`-site opnieuw
  opbouwt. `public/` staat in `.gitignore` — het wordt rechtstreeks als
  Pages-artifact gedeployed.
- De site is één pagina in Précon-huisstijl: `index.html` + `app.js`, met álle
  runs in `runs.js`. Bovenaan twee tegels (**Laatste dag** / **Laatste week**)
  die tegelijk de dag/week-schakelaar zijn; daaronder ◀ dropdown ▶ om door het
  hele archief te bladeren. Directe link naar één rapportage via de hash, bv.
  `…/#dag/2026-09-02` of `…/#week/2026-W35`.
- Handmatig bijdraaien: **Actions → Dagelijkse/Weekrapportage → Run workflow**
  (optioneel met een datum of weeknummer), of lokaal:

```bash
pip install -r requirements-ci.txt
python build_site.py daily --date 2026-09-02
python build_site.py weekly --week 35 --year 2026
python build_site.py rebuild          # alleen de site herbouwen uit data/
```

> De pipeline draait vanaf GitHub-runners, niet vanaf het Précon-netwerk. Bronnen
> die op IP blokkeren of streng rate-limiten (ECHA, FAVV, soms de SRU-endpoint)
> kunnen daardoor vaker als "API fout" in de rapportage staan dan lokaal.
> `http_client.py` doet nu retry-met-backoff (incl. `Retry-After`) om de 429's
> van `repository.overheid.nl` op te vangen.

## FIXED: officielebekendmakingen.nl SRU-API (Staatsblad, Staatscourant, Parlementair)

**Dit was het probleem dat ze meldde, en het is nu écht opgelost — niet
afgevangen als "handmatig checken".**

Het origineel praatte tegen `https://zoek.officielebekendmakingen.nl/sru/Search`.
Die endpoint is dood: de simpele datum+identifier-query geeft een kale HTTP
500 terug, en de product-area-query (gebruikt voor Parlementaire documenten)
geeft een nette maar fatale SRU-diagnostiek: `Invalid search field :
c.product-area`. Beide bevestigd door de exacte originele queries live tegen
de API te sturen.

De oorzaak: **KOOP heeft de SRU-endpoint verhuisd.** Onderzoek in KOOP's eigen
documentatie (Handleiding SRU 2.0 v1.4, gepubliceerd 2026-06-02 — dus ná het
bouwen van de originele tool in mei) wees naar de opvolger:
`https://repository.overheid.nl/sru`. Live getest: díe endpoint werkt gewoon,
met exact dezelfde CQL (`c.product-area==officielepublicaties`,
`dt.available==...`, `w.publicatienaam==...`). Voorbeeld: 4 Staatsblad-, 11
Staatscourant (Ministerie)-, 60 Staatscourant (Dienst/agentschap)- en 37
Parlementaire publicaties gevonden voor 14-08-2026, met échte titels en
werkende links. Eén veld werkte niet meer 1-op-1 over: `identifier any
"<prefix>"` geeft nu "Unsupported index" — dit is vervangen door filteren op
`w.publicatienaam` (zoals de Parlementair-query al deed) plus, voor
Staatscourant, client-side filteren op het `organisatietype`-veld dat toch al
in de respons zit.

`sources/sru.py` gebruikt nu de nieuwe endpoint. Dit is de grootste concrete
verbetering in deze rebuild: de drie bronnen die ze specifiek noemde als kapot
geven nu weer echte data terug.

## Twee bevestigde bugs in de bestaande tool (gevonden in haar eigen output)

Haar eigen `regulatory_results.csv` en `experimental_results_week18_2026.csv`
bevatten het bewijs voor twee concrete, losstaande bugs — dít zijn
waarschijnlijk (een deel van) de false positives die ze meldde, niet de
keyword-matching zelf (zie hieronder):

**1. `fetch_sccs` filtert helemaal niet op relevantie.** Elke link op de SCCS-
pagina die `opinion` of `publication` in de URL heeft wordt zonder
`is_relevant()`-check als "relevant, topic=Cosmetica" toegevoegd. Bewijs in
haar eigen CSV: entries als *"easy to read fact-sheets or web summaries"* en
*"Health & Food Safety Newsletters"* — dit zijn navigatielinks, geen
publicaties. Ze heeft dit zelf gemerkt: `experimental_monitor.py` bevat een
losse `experimental_monitor_seen.json`, die exact deze twee URL's elke week
opnieuw onderdrukt — een workaround voor het symptoom, niet een fix van de
oorzaak. Deze rebuild fixt de oorzaak: `fetch_sccs` gaat door dezelfde
`matcher.match()` als elke andere bron.

**2. `fetch_fod_vge` (FOD Volksgezondheid) plakt de breadcrumb-tekst van de
site vast aan de titel.** Bewijs in haar eigen CSV: *"Leefmilieu Gevaarlijke
stoffen en chemische producten Nieuw rapport over het financieringsmechanisme
voor PFAS-verontreiniging"* — "Leefmilieu Gevaarlijke stoffen en chemische
producten" is de categorie-breadcrumb van de site, aaneengeplakt vóór de
échte titel. Haar eigen code probeert dit al met een regex weg te knippen
(`^(Nieuws|Publicatie)\w*\s*`), maar de site plakt méér dan dat ene woord
ervoor, dus het lukt niet. Live onderzoek van de HTML wees uit dat elke
sectie een link heeft met een schoon `title="Ga naar: <titel>"` attribuut —
`sources/html_scrape.py::fetch_fod_vg` gebruikt dat in plaats van de
zichtbare (aaneengeplakte) linktekst.

## Wat níet gewijzigd is: de keyword-matching zelf

De config-export suggereerde dat de matching (leidende woordgrens i.p.v.
grens aan beide kanten) de oorzaak van false positives kon zijn. Met haar
echte `is_relevant()`-code en output-CSV's ernaast is daar geen bewijs voor
gevonden — dat gedrag is bewust en staat met reden in commentaar in haar
broncode ("zodat meervoud en vervoegingen ook matchen"). Deze rebuild volgt
daarom haar echte matching-logica exact (zie `matching.py`). Een strengere
variant (woordgrens aan beide kanten) is nog wel beschikbaar via
`RelevanceMatcher(config, strict_boundaries=True)`, voor wie 'm naast de
originele output wil vergelijken op echte data — maar het is nu expliciet
opt-in, niet de default.

## Overige bevindingen

- **EC Nieuws**: de presscorner zoek-API staat in haar code, maar is door
  haarzelf/een eerdere sessie al **uitgeschakeld** (`if False else None`, met
  commentaar "presscorner API niet beschikbaar"). Live testen bevestigt: de
  API geeft nu HTTP 404. EC Nieuws draait dus altijd op de RSS-feed alleen,
  die volgens haar eigen docstring maar ~10 items heeft en dus publicaties
  mist. Dit is een bekende, al geaccepteerde beperking — geen nieuw defect.
- **Twee gescheiden topic-keywordlijsten.** `regulatory_monitor.py` en
  `experimental_monitor.py` hebben allebei hun eigen `TOPIC_KEYWORDS`-dict,
  en de experimentele versie is een sterk verkorte kopie (bijv. "Elektrische
  apparaten" heeft 47 keywords in het hoofdscript, 9 in de experimentele
  versie). Een keyword toevoegen op één plek werkt niet door naar de andere.
  Deze rebuild heeft dat probleem niet: alles leest uit dezelfde
  `config/nonfood_monitor_config.json`.
- **Twee experimentele RSS-feeds zijn dood** (live bevestigd, 2026-08-17):
  `RVO (MVO/NL)` (`rvo.nl/rss/nieuws`) en `FOD Economie BE`
  (`economie.fgov.be/nl/rss/nieuws`) geven beide HTTP 404. Beide zijn
  experimenteel (alleen actief met `--experimental`) en falen netjes als
  `api_error`, maar de juiste, actuele feed-URL moet nog gevonden worden.
- **News - ECHA**: `echa.europa.eu` geeft HTTP 403 op de RSS-feed, ook met een
  browser User-Agent — dit was al voorzien in `MANUAL_CHECK_NOTES`.
- **Derde tab "Experimentele bronnen" in haar `app.py`** roept een apart
  script (`experimental_monitor.py`) aan met eigen memory-bestand. Deze
  rebuild heeft die experimentele bronnen wél (via `--experimental` /
  `EXPERIMENTAL_WEEKLY_SOURCES`), maar dan via dezelfde matcher/config als de
  rest — geen apart script met een eigen verouderde keywordlijst meer nodig.

## Projectstructuur

```
config/nonfood_monitor_config.json   topics, keywords, exclusieregels, bronnen
src/regulatory_monitor/
  config.py       config-loader
  matching.py      relevantie-matcher (poort van haar echte is_relevant())
  models.py        Publication / SourceCount
  pipeline.py       bronregistratie, run_sources, deduplicate
  export.py         CSV/JSON-export
  cli.py             command-line interface
  http_client.py     gedeelde requests-sessie
  sources/            één module per brontype (SRU, CELLAR SPARQL, sitemap,
                       RSS, HTML-scraping, Belgische bronnen)
app.py                Streamlit-dashboard
```

## IMPROVED: Documenten | NVWA was capturing almost nothing, not "a subset"

De originele `MANUAL_CHECK_NOTES` noemt dit "script pakt alleen subset". Live
onderzoek: van 125 gesamplede `/documenten/`-URL's op nvwa.nl had slechts **4
(~3%)** een YYYY/MM/DD-datum in het pad — en dat datumpatroon in de URL was
de *enige* manier waarop het origineel een publicatiedatum bepaalde. In de
praktijk kwam er dus vrijwel niets doorheen, geen "subset".

`sources/sitemap.py` valt terug op het `<lastmod>`-veld uit de sitemap zelf
wanneer de URL geen datum bevat (dezelfde aanpak die het origineel al wél
gebruikte voor de bron "ROW"). Live getest: dit haalt nu 105 documenten op in
een periode van 14 dagen, tegen vrijwel 0 met de oude URL-only-aanpak.
Kanttekening: anders dan bij ROW is er geen bevestiging dat NVWA's `lastmod`
altijd de echte publicatiedatum is en niet zomaar "laatst technisch
aangeraakt" — de moeite waard om een paar weken tegen nvwa.nl zelf te
steekproeven voordat je de teller blind vertrouwt.

## FIXED: E-justice België (Justel) was gemarkeerd als "niet automatiseerbaar"

De config had Justel op `"type": "handmatig"` staan ("JavaScript vereist"). Dat
klopt voor de interactieve zoekpagina (`rech.pl`), maar niet voor de
resultatenlijst: **`cgi_loi/list.pl?language=nl&pdd=<van>&pdf=<tot>`** geeft
volledig server-side gerenderde HTML terug met een filter op publicatiedatum —
exact dezelfde truc als `summary.pl` bij het Belgisch Staatsblad en de maandlijst
bij refLex. `sources/belgium.py::fetch_justel` pagineert die lijst (30/pagina),
parseert categorie / titel / publicatiedatum / NUMAC per rij, slaat
vertaal-herpublicaties over ("- Duitse vertaling" e.d.) en matcht op de titel.

Draait op **weekcadans**: de Justel-index loopt enkele dagen achter op het
Staatsblad, dus voor een sluitende telling draai je zo nodig ook de voorgaande
week. Live getest: week 32/2026 → 48 akten, 3 relevant (o.a. de omzetting van
Richtlijn (EU) 2024/825). Justel is de genormeerde subset van het Staatsblad
(wetten, KB's, MB's, decreten, besluiten) mét onderwerpsclassificatie, dus
hogere precisie dan de ruwe Staatsblad-scrape.

## Genuine dead ends — checked live, not fixable without real extra engineering

- **FAVV publicaties/nieuws** (favv-afsca.be): live bevestigd dat dit een
  echte anti-bot-pagina is (Drupal "antibot"-module, `class="script-disabled"`
  in de HTML), niet een simpele header-blokkade — HTTP 200, maar de body is
  een JS-challenge-pagina in plaats van RSS. Alleen op te lossen met een
  echte headless browser (Playwright/Selenium) die JavaScript uitvoert. Beide
  libraries zijn al eens getest in haar `.claude/settings.local.json`
  (`import playwright`, `import selenium`) maar nooit daadwerkelijk in een
  fetcher verwerkt — dat is een reëel vervolgproject, geen quick fix.
- **News - ECHA**: `echa.europa.eu` blokkeert niet alleen de RSS-feed maar de
  hele site (HTTP 403 op zowel `/nl/rss/news` als `/nl/news`), met een browser
  User-Agent. Dat wijst op een IP-/geoblock op serverniveau, niet op iets in
  de request zelf. **Belangrijke kanttekening:** dit is getest vanaf de
  omgeving waarin dit project gebouwd is — als zij dit vanaf haar eigen
  kantoor-/thuisnetwerk draait, kan het gewoon werken. Dit zou als eerste
  getest moeten worden op haar eigen machine voor je concludeert dat het echt
  stuk is.
- **refLex Chrono BE**: telling via de maandlijst kan afwijken van de echte
  zoekpagina — altijd handmatig verifiëren (dit is inherent aan de aanpak,
  niet iets dat met betere code oplosbaar is).
- **RVO (MVO/NL)** en **FOD Economie BE** (experimentele bronnen): beide
  RSS-feed-URL's uit het origineel geven nu HTTP 404. Een korte zoektocht naar
  de vervangende feed-URL leverde niets op — dat vraagt handmatig uitzoeken
  op de sites zelf.

## Wat dit betekent voor "volledig werkend krijgen"

Van de bronnen die ooit alleen-handmatig waren: **4 daagse kernbronnen zijn nu
echt gefixt** (Staatsblad, Staatscourant × 2, Parlementair), **NVWA Documenten
is van vrijwel-niets naar bruikbaar** gegaan, en **Justel draait nu wekelijks**
via `list.pl`. FAVV en ECHA blijven staan — de eerste is een apart, groter
project (browser-automatisering), de tweede moet eerst getest worden vanaf haar
eigen netwerk voordat je "stuk" concludeert.
