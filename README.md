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
- ⚙️ **Indstillinger for kalenderen** — vælg hvilke tilmeldingsstatusser og
  aktivitetstyper der skal med, og se status direkte i begivenhedens titel
- 📩 **Beskeder fra trænere/klub** — seneste 10 med fuld body cached lokalt
- ✅ **Tilmeld og frameld aktiviteter** — framelding kræver en kommentar
- 🔁 **Multi-barn-støtte** — nye børn opdages automatisk og får entiteter uden
  genstart af Home Assistant
- 🔐 **UI-baseret config** — brugernavn/password gemmes krypteret i HA

## Hvordan børn findes

`mit.dbu.dk/MyTeam/MyTeams.aspx` er en **vælger**: har du flere børn, får du
en tabel med ét hold pr. barn ("Som forælder/kontaktperson"). Har du kun ét,
springer DBU vælgeren over og viser holdet direkte — det er derfor
integrationen virkede fint indtil barn nr. 2 kom til.

Holdet vælges ikke med en URL, men med en ASP.NET-postback, der lander på
`PlayerTeam.aspx`. Integrationen gør derfor:

1. Henter vælgeren og læser alle rækker — det er den eneste komplette liste
   over børn på mit.dbu.dk, og den viser også børn helt uden aktiviteter.
2. Poster rækkens `__doPostBack`-mål for hvert barn og henter holdsiden, som
   selv oplyser klub, hold, "Kontaktperson for: *navn*" og aktiviteterne.
3. Bruger hold-ID'et (fra holdsidens iCal-link) som barnets faste nøgle, og
   gemmer den i `.storage/kampklar.children.<entry_id>` så entiteternes
   `unique_id` ligger fast — også når holdet skifter navn ved sæsonskifte.

Forsiden bruges ikke til at finde børn: den viser kun de førstkommende fire
begivenheder på tværs af alle børn, så med to børn falder det ene typisk helt
ud.

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

Et færdigt dashboard ligger i [`dashboard.yaml`](dashboard.yaml), med overblik,
kalender, beskeder og et kort til tilmelding/framelding.

1. Kopiér [`www/kampklar-activities-card.js`](www/kampklar-activities-card.js)
   til `www/kampklar-activities-card.js` i din Home Assistant-config. Filen skal
   kopieres separat; installation af integrationen via HACS kopierer ikke kortet.
2. Registrér `/local/kampklar-activities-card.js?v=5` som **JavaScript module**
   under **Settings → Dashboards → Resources** (kræver Advanced Mode).
3. Indsæt `dashboard.yaml` via **Settings → Dashboards → Add Dashboard →
   Raw configuration editor**. Genindlæs browseren efter registrering af kortet.

Ved YAML-styrede resources tilføjes dette under `lovelace` i `configuration.yaml`:

```yaml
lovelace:
  resources:
    - url: /local/kampklar-activities-card.js?v=5
      type: module
```

Flet ind i en eksisterende `lovelace`-konfiguration i stedet for at oprette nøglen
to gange. Hvis et YAML-dashboard bruger UI-styrede resources, registreres kortet
fortsat i UI'en. Ved opdatering af JS-filen ændres `?v=5` til fx `?v=6`.
Kortets JS-fil og dashboardet kan også hentes som separate assets på release-siden.

Det er skrevet navne-uafhængigt: alle børn hentes fra `sensor.kampklar_boern`,
så et nyt barn dukker op af sig selv. Kun kalender-kortet skal have hvert
barns kalender skrevet ind i hånden — det kort kan ikke tage en dynamisk
liste. Både `sensor.kampklar_boern` og `sensor.kampklar_born` understøttes.

### Tilføj kortet til et eksisterende dashboard

Behold dit dashboard og indsæt dette i en fanes `cards`-liste:

```yaml
- type: custom:kampklar-activities-card
  title: Kommende aktiviteter
```

På en fane for et bestemt barn kan kortet filtreres med `child` (barnets
`short_name` fra children-attributten):

```yaml
- type: custom:kampklar-activities-card
  child: Emil
```

Kortet viser alle kommende aktiviteter i én samlet liste sorteret efter dato
og tidspunkt, også dem der allerede er besvaret. Barnets navn står på hver
aktivitet. Hver række viser titel, dato, tidspunkt og status med
**Tilmeld** og **Frameld** direkte på rækken. **Frameld** åbner et kommentarfelt;
skriv begrundelsen og tryk **Send afbud**. **Annuller** lukker formularen uden
at sende noget. **Tilmelding lukket** skjuler kun Tilmeld-knappen: afbud kan
stadig være muligt, fx når barnet er tilmeldt som standard. DBU validerer den
konkrete handling. Fejl vises i kortet, og kommentarer beholdes ved opdateringer
og fejl.
Kortet erstatter den separate aktivitetsliste. Beskedsvar er ikke implementeret.

Hvis kontoens sensor har et andet entity-id, angives `children_entity`.
Ved flere Kampklar-konti angives også kontoens `config_entry_id` i kortets YAML,
så handlingerne sendes til den rigtige konto. Kortet har ingen ekstra
HACS-afhængigheder og kræver ingen input-hjælpere.

## Indstillinger

**Settings → Devices & Services → Kampklar → Konfigurer.**

Kalenderen bliver hurtigt støjende når hvert barn har både træning, kampe og
stævner. Derfor:

- **Typen står foran titlen** — `Kamp: Vestby IF - Nabolaget B` og
  `Træning: Træning på Bane 2`, så en kamp kan skelnes fra en træning direkte
  i kalenderen. Kan slås fra.
- **Status står kun i titlen når den afviger** — `Træning på Kunsten
  (Frameldt)`, `Vestby IF - Nabolaget B (Ikke svaret)`. Er alt som det skal
  være, er titlen ren. Du vælger selv hvilke statusser der regnes som
  afvigende; som udgangspunkt er det Frameldt, Ikke svaret, Udtaget (ikke
  bekræftet), Til rådighed og Andet.
- **Statusfiltret er pr. aktivitetstype.** Ved træning er status kun
  interessant hvis du har meldt fra — derfor er **frameldt træning skjult fra
  start**, mens kampe viser alt, så du også ser dem du endnu ikke har svaret
  på. Begge dele kan ændres.
- **Aktivitetstyper** — tom betyder alle. Listen bygges af de typer din klub
  rent faktisk bruger, og der er ét statusfelt pr. type.

DBU's statusser: Tilmeldt · Udtaget (bekræftet) · Udtaget · Udtaget (ikke
bekræftet) · Til rådighed · Ikke svaret · Frameldt · Andet. Sidstnævnte fanger
statusser vi ikke kender endnu — de bliver vist, ikke skjult.

Indstillingerne gælder kun kalenderen. Sensorerne viser altid alt, og hver
aktivitet bærer både `signup_status` (DBU's ordlyd) og `signup_status_key`
(fast nøgle) til brug i templates. Begivenhedens beskrivelse har stadig type,
status, mødetid og pulje — også når titlen er ren.

## Tilmelding og framelding

Aktivitets-ID'et står som `id` i `activities`-attributten på sensorerne for
kommende aktiviteter og manglende tilmelding. Brug integrationens actions fra
et dashboard, script eller en automatisering:

```yaml
# Tilmeld
- action: kampklar.tilmeld
  data:
    activity_id: 6950992

# Frameld — kommentar er obligatorisk
- action: kampklar.frameld
  data:
    activity_id: 6950992
    comment: "Er syg"
```

Har Home Assistant flere Kampklar-konti, vælges den ønskede konto i actionens
felt **Kampklar-konto**. Efter handlingen henter integrationen straks den nye
status fra DBU.

Fra v0.6.3 vælger integrationen altid det rigtige barn/hold i DBU-sessionen før
en skrivehandling. Opdatér integrationen til mindst v0.6.3, før du bruger det
nyeste dashboardkort (som sender `child_key`). Datahentning og skrivehandlinger køres én ad gangen, så de ikke
skifter sessionens barn undervejs. Dashboardkortet sender også `child_key`
automatisk. Ved manuelle actions kan feltet udelades, hvis aktivitets-ID'et kun
findes hos ét barn; ellers angives barnets `key` fra children-attributten.

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
Er barnet ikke med, stod det heller ikke i KampKlar-vælgeren — slå debug-log
til og genindlæs integrationen:

```yaml
logger:
  logs:
    custom_components.kampklar: debug
```

**Et barn hænger ved efter det er meldt ud.** Det forsvinder af sig selv ved
næste opdatering, når rækken er væk fra KampKlar-vælgeren. Vil du rydde op med
det samme: slet enheden under **Settings → Devices & Services → Kampklar**.

**Dubletter af enheder uden entiteter.** Gamle integrationer brugte andre
interne ID'er, og tomme enheder kan være blevet efterladt under migreringen.
Fra v0.6.2 kan de slettes via enhedens side → ⋮ → Slet. Integrationen tillader
kun sletning af enheder uden entiteter; aktive enheder beskyttes.

**Ingen børn overhovedet.** Loggen siger hvad siden indeholdt. Står der at
KampKlar-siden hverken havde hold eller vælger, har DBU lagt siden om igen —
åbn et issue.

## Begrænsninger

- mit.dbu.dk eksponerer ikke "læst/ulæst"-status i indbakkelisten — vi viser
  bare de seneste 10 beskeder uanset.
- Tilmelding og framelding bruger mit.dbu.dk's ASP.NET-formularer, da DBU ikke
  stiller et officielt skrive-API til rådighed. Sideændringer hos DBU kan derfor
  kræve en opdatering af integrationen.
- Kalender-kortet i Lovelace kan ikke tage en dynamisk entity-liste, så nye
  børn skal tilføjes der i hånden.

## Udvikling

POC-script + parsere ligger i [`scripts/`](scripts/). Sæt en venv op:

```bash
cd scripts
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
node --test test_dashboard.mjs
```

Testene kører mod anonymiserede fixtures i [`scripts/fixtures/`](scripts/fixtures/)
— udklip af den rigtige markup med opdigtede navne, hold og id'er:

| Fixture | Side |
|---|---|
| `myteams_chooser.html` | KampKlar-vælgeren med to børn (`__VIEWSTATE` er en dummy — den rigtige indeholder persondata) |
| `playerteam_emil.html`, `playerteam_ida.html` | Holdsiden efter postback, ét pr. barn |
| `myteams_emil.html` | Holdsiden serveret direkte, som når kontoen kun har ét barn |
| `dashboard.html` | Forsiden, hvor kun det travleste barn er med |
| `inbox.html`, `message.html` | Beskedcenteret |

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
