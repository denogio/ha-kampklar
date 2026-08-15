# Kampklar — Home Assistant integration for mit.dbu.dk

Henter dine børns fodboldaktiviteter, kampe og beskeder fra
[mit.dbu.dk](https://mit.dbu.dk) ind i Home Assistant.

## Features

- 🗓️ **Kalender pr. barn** — alle kommende aktiviteter som HA `CalendarEntity`
- ⚽ **Sensorer pr. barn**:
  - Næste aktivitet (timestamp + lokation, type, tilmeldingsstatus)
  - Kommende aktiviteter (state = antal, attribut = fuld liste)
  - Mangler tilmelding (state = antal aktiviteter du skal svare på)
- 👨‍👩‍👦 **Samlede sensorer for hele kontoen** — næste aktivitet, manglende
  tilmeldinger og et overblik over alle børn ét sted
- 📩 **Beskeder fra trænere/klub** — seneste 10 med fuld body cached lokalt
- 🔁 **Multi-barn-støtte** — nye børn opdages automatisk og får entiteter uden
  genstart af Home Assistant
- 🔐 **UI-baseret config** — brugernavn/password gemmes krypteret i HA

## Hvordan børn findes

mit.dbu.dk har ingen "mine børn"-side. Forsiden viser kun de **førstkommende
~4 begivenheder på tværs af alle børn** — har det ene barn fire aktiviteter
før det andets første, står barn nr. 2 slet ikke der. Derfor:

1. Forsiden bruges kun til at *opdage* nye børn.
2. Alle børn vi har set før gemmes i Home Assistants storage
   (`.storage/kampklar.children.<entry_id>`), så de ikke forsvinder igen.
3. Hvert barn verificeres ved at hente dets KampKlar-side, som selv oplyser
   klub, hold og "Kontaktperson for: *navn*". Det virker også når barnet ikke
   har nogen aktiviteter lige nu.
4. Er et barn ikke længere tilknyttet kontoen, holder DBU op med at vise dets
   hold, og barnet falder ud af listen igen ved næste opdatering.

## Installation

### Via HACS (anbefalet)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=denogio&repository=ha-dbu-kampklar&category=integration)

1. Klik på badge'et ovenfor (eller manuelt: HACS → Integrations → tre prikker → "Custom repositories" → tilføj `https://github.com/denogio/ha-dbu-kampklar` som *Integration*)
2. Installer "Kampklar (mit.dbu.dk)" og genstart Home Assistant
3. Tilføj integrationen:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kampklar)

(eller manuelt: **Settings → Devices & Services → Add Integration → "Kampklar"**) og indtast dine DBU-credentials.

### Manuelt

Kopiér `custom_components/kampklar/` til din HA-config's `custom_components/`,
genstart, og tilføj integrationen via UI'en.

## Entity-IDs

Én enhed for hele kontoen:

- `sensor.kampklar_boern` — antal børn; attributten `children` har ét opslag
  pr. barn med navn, hold, klub, næste aktivitet, tællere og barnets egne
  entity-id'er
- `sensor.kampklar_naeste_aktivitet` — den førstkommende aktivitet uanset barn
- `sensor.kampklar_mangler_tilmelding` — samlet antal ubesvarede tilmeldinger
- `sensor.kampklar_beskeder`

Plus én enhed pr. barn, hvor `<navn>` er barnets fornavn fra mit.dbu.dk
(`Emil` og `Ida` er bare eksempler):

- `sensor.kampklar_<navn>_naeste_aktivitet`
- `sensor.kampklar_<navn>_kommende_aktiviteter`
- `sensor.kampklar_<navn>_mangler_tilmelding`
- `calendar.kampklar_<navn>_aktiviteter`

Har to børn samme fornavn — eller er ét barn på to hold — får de holdnavn
tilføjet, så entity-id'erne aldrig kolliderer.

## Dashboard

Et færdigt dashboard ligger i [`dashboard.yaml`](dashboard.yaml). Indsæt via
**Settings → Dashboards → Add Dashboard → Raw configuration editor**.

Det er skrevet navne-uafhængigt: alle børn hentes fra `sensor.kampklar_boern`,
så et nyt barn dukker op af sig selv. Kun kalender-kortet skal have hvert
barns kalender skrevet ind i hånden — det kort kan ikke tage en dynamisk
liste.

## Automatiseringer

Eksempler ligger i [`automations/kampklar.yaml`](automations/kampklar.yaml):

- Push ved ny besked
- Push ved ny planlagt aktivitet (dækker alle børn automatisk)
- 2 timer før-påmindelse (via calendar trigger — én trigger pr. barn)
- Daglig påmindelse om manglende tilmelding, med barnets navn i beskeden

Notifikationerne åbner Kampklar-dashboardet ved tryk via `clickAction`. Ret
`notify.mobile_app_min_telefon` til din egen notify-service.

## Hvor ofte poller den?

Hver 60 minutter. Tilrettes i [`custom_components/kampklar/const.py`](custom_components/kampklar/const.py).

## Fejlfinding

**Et barn mangler.** Kig på attributten `children` på `sensor.kampklar_boern`.
Er barnet ikke med, har integrationen hverken set det på forsiden eller gemt
det tidligere — slå debug-log til og genindlæs integrationen:

```yaml
logger:
  logs:
    custom_components.kampklar: debug
```

**Et barn hænger ved efter det er meldt ud.** Det forsvinder af sig selv ved
næste opdatering, når DBU holder op med at vise dets hold. Vil du rydde op med
det samme: slet enheden under **Settings → Devices & Services → Kampklar**.

## Begrænsninger

- mit.dbu.dk eksponerer ikke "læst/ulæst"-status i indbakkelisten — vi viser
  bare de seneste 10 beskeder uanset.
- Afmelding fra aktiviteter er endnu ikke implementeret (på roadmap).
- Kalender-kortet i Lovelace kan ikke tage en dynamisk entity-liste, så nye
  børn skal tilføjes der i hånden.

## Udvikling

POC-script + parsere ligger i [`scripts/`](scripts/). Sæt en venv op:

```bash
cd scripts
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest test_parsers.py
```

Testene kører mod anonymiserede fixtures i [`scripts/fixtures/`](scripts/fixtures/)
— udklip af den rigtige markup med opdigtede navne, hold og id'er. `dashboard.html`
viser med vilje kun ét barns aktiviteter, så to-børns-tilfældet er dækket.

Vil du hente friske sider fra din egen konto:

```bash
cp .env.example .env  # tilret med dine credentials
.venv/bin/python poc_login.py
```

De havner i `scripts/dumps/` — den mappe er gitignored og skal blive der,
for siderne indeholder navne, telefonnumre og beskedindhold. Det samme
gælder HAR-filer fra browserens netværksfane: de indeholder også dit login.

## License

MIT
