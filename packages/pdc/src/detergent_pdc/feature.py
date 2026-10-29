"""Protein-detergent simulations: the pdc run type, its panel API and the code paths it took over."""
from dashboard import features

from .execution.adapters import pdc
from .web.routes import pdc as pdc_routes

FEATURE = features.Feature(
    name='pdc',
    blueprints=(pdc_routes.blueprint,),
    protocols={'pdc': lambda: pdc.PROTOCOL},
    # A prepared pdc run records the engine spelling `dashboard/execution/scripts/pdc_*.sh`; the files live here now,
    # and the resolver looks for them in this distribution before the engine's own scripts directory.
    code_prefixes=(('dashboard/execution/scripts/', 'detergent_pdc', 'execution/scripts/'),),
)
