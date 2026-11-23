"""Group a delivery of RDF files into knowledge graphs.

Accepted shapes (mixable in one batch):

* one file per KG                     ``retail.ttl``                -> KG ``retail``
* split schema/instances files         ``energy_tbox.nt`` + ``energy_abox.nt`` -> KG ``energy``
* one folder per KG                    ``finance/TBox.ttl`` + ``finance/ABox.ttl`` -> KG ``finance``
* explicit role folders (the UI)       ``finance/tbox/x.ttl`` + ``finance/abox/y.ttl`` -> KG ``finance``
* zip archives of any of the above     ``kgs.zip`` (a zip whose files sit at its root is one KG named after the zip)

Every KG gets a **TBox** (schema: classes, properties, axioms) and an **ABox** (instances), as in the
KG2MD notebook. A file's role comes from an explicit ``tbox``/``abox`` folder, else from its name
(``*_tbox``, ``*schema*``, ``*_abox``, ``*data*`` ...), else from its content: a combined file is split,
schema triples to the TBox and the rest to the ABox.

A file whose triples are all ``owl:sameAs`` is treated as an identity graph, not a KG.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rdflib import Graph
from rdflib.namespace import OWL, RDF, RDFS

FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".rdf": "xml", ".owl": "xml", ".xml": "xml",
           ".jsonld": "json-ld", ".json-ld": "json-ld", ".nq": "nquads", ".trig": "trig"}
ROLE_SUFFIX = re.compile(r"[-_. ]*(tbox|abox|schema|ontology|onto|data|instances|kg)$", re.I)
ROLE_ONLY = re.compile(r"^(tbox|abox|schema|ontology|onto|data|instances)$", re.I)
TBOX_WORDS = re.compile(r"(?:^|[-_. ])(tbox|schema|ontology|onto)(?:$|[-_. ])", re.I)
ABOX_WORDS = re.compile(r"(?:^|[-_. ])(abox|data|instances)(?:$|[-_. ])", re.I)
SCHEMA_TYPES = {OWL.Class, RDFS.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty, RDF.Property,
                OWL.Ontology, OWL.Restriction, OWL.FunctionalProperty, OWL.TransitiveProperty, OWL.SymmetricProperty,
                OWL.InverseFunctionalProperty}
SCHEMA_PREDICATES = {RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range, OWL.equivalentClass,
                     OWL.equivalentProperty, OWL.inverseOf, OWL.disjointWith, OWL.imports}


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
    """KG name from a relative path: the nearest folder that is not a role folder (tbox/abox/...),
    else the file stem minus its TBox/ABox role."""
    p = PurePosixPath(path)
    folders = [d for d in p.parts[:-1] if not ROLE_ONLY.match(d)]
    if folders:
        return slug(folders[-1]) or "kg"
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


def file_role(path: str) -> str | None:
    """'tbox' / 'abox' from an explicit folder or the file name; None when the file does not say."""
    p = PurePosixPath(path)
    for d in reversed(p.parts[:-1]):
        if re.fullmatch(r"tbox|schema|ontology|onto", d, re.I):
            return "tbox"
        if re.fullmatch(r"abox|data|instances", d, re.I):
            return "abox"
    stem = p.name.split(".")[0]
    if TBOX_WORDS.search(stem):
        return "tbox"
    if ABOX_WORDS.search(stem):
        return "abox"
    return None


def split_schema(g: Graph) -> tuple[Graph, Graph]:
    """Split a combined graph: triples about schema entities (or schema axioms) -> TBox, the rest -> ABox."""
    schema = {s for s, _, o in g.triples((None, RDF.type, None)) if o in SCHEMA_TYPES}
    tbox, abox = Graph(), Graph()
    for t in g:
        (tbox if t[0] in schema or t[1] in SCHEMA_PREDICATES else abox).add(t)
    return tbox, abox


@dataclass
class KgInput:
    """One knowledge graph of a delivery, with its TBox and ABox kept apart."""

    name: str
    tbox: Graph
    abox: Graph
    tbox_files: list[str]
    abox_files: list[str]


def _add(target: Graph, g: Graph) -> None:
    for t in g:
        target.add(t)
    for prefix, uri in g.namespaces():
        target.bind(prefix, uri, override=False)


def group(files: list[RdfFile]) -> tuple[dict[str, KgInput], list[tuple[str, Graph]]]:
    """-> ({kg name: KgInput}, [(path, identity graph)])."""
    kgs: dict[str, KgInput] = {}
    identity: list[tuple[str, Graph]] = []
    for f in expand(files):
        g = parse(f)
        if is_identity_graph(g):
            identity.append((f.path, g))
            continue
        name = kg_name(f.path)
        kg = kgs.setdefault(name, KgInput(name, Graph(), Graph(), [], []))
        role = file_role(f.path)
        if role == "tbox":
            _add(kg.tbox, g)
            kg.tbox_files.append(f.path)
        elif role == "abox":
            _add(kg.abox, g)
            kg.abox_files.append(f.path)
        else:  # combined file: split by content
            tb, ab = split_schema(g)
            _add(kg.tbox, tb)
            _add(kg.abox, ab)
            for prefix, uri in g.namespaces():
                kg.tbox.bind(prefix, uri, override=False)
                kg.abox.bind(prefix, uri, override=False)
            kg.tbox_files.append(f.path)
            kg.abox_files.append(f.path)
    return dict(sorted(kgs.items())), identity
