"""Test fixtures: the thesis' benchmark KGs (generated raw RDF with the audited numbers)."""
from fixtures.enterprise import build_enterprise_benchmark


def load_enterprise(az, domains: list[str] | None = None) -> None:
    """Load the seven raw domain KGs (each through KG2MD) plus their identity graph into ``az``."""
    bm = build_enterprise_benchmark()
    for name, g in bm.graphs.items():
        if domains is None or name in domains:
            az.load_kg(name, g)
    az.load_identity(bm.identity)
