"""Module contracts for progressive backend/frontend organization.

Single backend is preserved. This package only defines module boundaries
and contracts to keep growth incremental and clean.
"""

from .registry import MODULE_CONTRACTS, ModuleContract, get_contract, iter_contracts

__all__ = [
    "MODULE_CONTRACTS",
    "ModuleContract",
    "get_contract",
    "iter_contracts",
]

