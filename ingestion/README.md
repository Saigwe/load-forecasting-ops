# Ingestion (roadmap)

Loaders for the real data go here and write to the same `bronze` tables as the fixture.

Real data: the [NESO data portal](https://www.neso.energy/data-portal) (formerly National Grid ESO) historic GB demand, half-hourly, with weather from the [Open-Meteo API](https://open-meteo.com/). CI uses a synthetic half-hourly demand and daily weather fixture.
