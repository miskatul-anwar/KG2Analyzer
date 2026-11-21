"""Group a delivery of RDF files into knowledge graphs.

Accepted shapes (mixable in one batch):

* one file per KG                     ``retail.ttl``                -> KG ``retail``
* split schema/instances files         ``energy_tbox.nt`` + ``energy_abox.nt`` -> KG ``energy``
* one folder per KG                    ``finance/TBox.ttl`` + ``finance/ABox.ttl`` -> KG ``finance``
* zip archives of any of the above     ``kgs.zip`` (a zip whose files sit at its root is one KG named after the zip)

A file whose triples are all ``owl:sameAs`` is treated as an identity graph, not a KG.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rdflib import Graph
from rdflib.namespace import OWL

FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".rdf": "xml", ".owl": "xml", ".xml": "xml",
           ".jsonld": "json-ld", ".json-ld": "json-ld", ".nq": "nquads", ".trig": "trig"}
ROLE_SUFFIX = re.compile(r"[-_. ]*(tbox|abox|schema|ontology|onto|data|instances|kg)$", re.I)
ROLE_ONLY = re.compile(r"^(tbox|abox|schema|ontology|onto|data|instances)$", re.I)


@dataclass
class RdfFile:
    path: str  # relative path inside the delivery (folders matter: they name the KG)
    data: bytes

    @property
    def fmt(self) -> str | None:
        return FORMATS.get(PurePosixPath(self.path).suffix.lower())


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def kg_name(path: str) -> str:
    """KG name from a relative path: the parent folder if any, else the file stem minus its TBox/ABox role."""
    p = PurePosixPath(path)
    if len(p.parts) > 1:
        return slug(p.parts[-2]) or "kg"
    stem = p.name.split(".")[0]
    if ROLE_ONLY.match(stem):
        return "kg"
    return slug(ROLE_SUFFIX.sub("", stem)) or slug(stem) or "kg"


def expand(files: list[RdfFile]) -> list[RdfFile]:
    """Unpack zip archives; keep RDF files only."""
    out: list[RdfFile] = []
    for f in files:
        if f.path.lower().endswith(".zip"):
            base = ROLE_SUFFIX.sub("", PurePosixPath(f.path).stem) or "kg"
            with zipfile.ZipFile(io.BytesIO(f.data)) as z:
                for info in z.infolist():
                    if info.is_dir() or "__MACOSX" in info.filename or PurePosixPath(info.filename).name.startswith("."):
                        continue
                    inner = PurePosixPath(info.filename)
                    rel = str(inner) if len(inner.parts) > 1 else f"{base}/{inner.name}"
                    out.append(RdfFile(rel, z.read(info)))
        elif f.fmt:
            out.append(f)
    return [f for f in out if f.fmt]


def read_paths(paths: list[str | Path]) -> list[RdfFile]:
    """Files, directories (walked recursively; sub-folders name KGs) and zip archives on disk."""
    out: list[RdfFile] = []
    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    out.append(RdfFile(f.relative_to(p).as_posix(), f.read_bytes()))
        elif p.is_file():
            out.append(RdfFile(p.name, p.read_bytes()))
        else:
            raise FileNotFoundError(p)
    return out


def parse(f: RdfFile) -> Graph:
    g = Graph()
    try:
        g.parse(data=f.data.decode("utf-8"), format=f.fmt)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{f.path}: not valid {f.fmt} ({str(e)[:200]})") from e
    return g


def is_identity_graph(g: Graph) -> bool:
    return len(g) > 0 and all(p == OWL.sameAs for _, p, _ in g)


def group(files: list[RdfFile]) -> tuple[dict[str, tuple[Graph, list[str]]], list[tuple[str, Graph]]]:
    """-> ({kg name: (merged graph, source paths)}, [(path, identity graph)])."""
    kgs: dict[str, tuple[Graph, list[str]]] = {}
    identity: list[tuple[str, Graph]] = []
    for f in expand(files):
        g = parse(f)
        if is_identity_graph(g):
            identity.append((f.path, g))
            continue
        name = kg_name(f.path)
        merged, paths = kgs.setdefault(name, (Graph(), []))
        for t in g:
            merged.add(t)
        for prefix, uri in g.namespaces():
            merged.bind(prefix, uri, override=False)
        paths.append(f.path)
    return dict(sorted(kgs.items())), identity
