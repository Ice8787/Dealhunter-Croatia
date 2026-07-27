# DealHunter Grocery Croatia v2

Fokus: Kroatien och kedjorna Konzum, Plodine, Lidl Hrvatska och Kaufland Hrvatska.

## Funktioner
- Automatisk daglig prisinsamling via GitHub Actions
- Hela upptäckta prisregistret, inte bara kampanjvaror
- Sökning, kategori- och butiksfilter
- Jämförpris per kg, liter eller styck
- Jämförelse mellan butiker
- Favoriter
- Inköpslista
- Smart Basket med uppskattad resekostnad
- Källstatus per butik

## Filstruktur

GitHub kräver att workflow-filen ligger exakt här:

`.github/workflows/update-prices.yml`

Övriga insamlingsfiler ligger i `scrapers/`.

## Installation från mobil

1. Ladda upp rotfilerna:
   - index.html
   - manifest.webmanifest
   - prices.json
   - requirements.txt
   - README.md
2. Skapa filerna via `Add file → Create new file` med hela sökvägen:
   - `.github/workflows/update-prices.yml`
   - `scrapers/update_prices.py`
   - `scrapers/stores.json`
   - `scrapers/watchlist.json`
3. Under `Settings → Actions → General`, välj `Read and write permissions`.
4. Under `Settings → Pages`, välj `GitHub Actions`.
5. Öppna `Actions → Update Croatian grocery prices → Run workflow`.

## Viktigt
Kedjornas prislistesidor och format kan ändras. Dashboarden visar därför status för varje källa. En trasig källa stoppar inte de andra.
