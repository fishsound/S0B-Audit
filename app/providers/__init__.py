"""
Provider registry.

To add a new data source:
  1. Create app/providers/your_source.py
  2. Subclass BaseProvider and implement enrich_characters()
  3. Import and append to EXTRA_PROVIDERS below

The audit engine calls every provider in EXTRA_PROVIDERS after the primary
Alliance Auth and ESI providers have run, passing the same character list
so each provider can add data to character.provider_data["your_source"].
"""
from app.providers.auth_scraper import AllianceAuthProvider
from app.providers.esi import ESIProvider

# Register additional data-source providers here when ready.
# Each entry must be an instantiated BaseProvider subclass.
EXTRA_PROVIDERS: list = []
