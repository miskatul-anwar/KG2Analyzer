"""Read MDKGs as the KG2MD notebook writes them.

One KG's MDKG is the notebook's output folder::

    <kg>/factclass_selection.json
    <kg>/kg2md.log
    <kg>/fact_classes/<FactClass>_<hash>/mdkg_schema.ttl     QB4OLAP schema graph
    <kg>/fact_classes/<FactClass>_<hash>/mdkg_data.ttl       observations, level members, rollup edges
    <kg>/fact_classes/<FactClass>_<hash>/mdkg_dataset.nq     self-contained bundle: source + schema + cube graphs

``read_mdkgs`` accepts those folders (or a zip of them, or a single bundle), plus ``owl:sameAs``
files, and returns per KG its source, schema and data graph. A bundle is preferred; a cube folder
without one needs both ``mdkg_schema.ttl`` and ``mdkg_data.ttl`` (it then has no source graph).
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from rdflib import Dataset, Graph, Literal, URIRef
from rdflib.namespace import RDF

from kg2analyzer.ingest import RdfFile, is_identity_graph, parse, slug

MDKG = "http://example.org/mdkg/"
SOURCE_GRAPH, SCHEMA_GRAPH, CUBE_GRAPH, VIEWS_GRAPH = (URIRef(MDKG + n) for n in
                                                       ("sourceGraph", "schemaGraph", "cubeGraph", "viewsGraph"))
QB4O_MEMBER_OF = URIRef("http://purl.org/qb4olap/cubes#memberOf")
QB_DATASET = URIRef("http://purl.org/linked-data/cube#DataSet")
HINT = ("is not an MDKG. Build it in step 1 and load the saved folder (or mdkg.zip): "
        "<kg>/fact_classes/<cube>/mdkg_dataset.nq, or mdkg_schema.ttl + mdkg_data.ttl.")


@dataclass
class Mdkg:
    name: str
    source: Graph = field(default_factory=Graph)
    schema: Graph = field(default_factory=Graph)
    data: Graph = field(default_factory=Graph)
    cubes: list[str] = field(default_factory=list)       # cube folder names (<FactClass>_<hash>)
    files: list[str] = field(default_factory=list)
    selection: dict | None = None                         # factclass_selection.json
    raw: dict[str, bytes] = field(default_factory=dict)   # every file as loaded, for re-saving


def _expand(files: list[RdfFile]) -> list[RdfFile]:
    """Unpack zips (all members, not only RDF). A zip whose cube folders sit at its root is one KG named after it."""
    out: list[RdfFile] = []
    for f in files:
        if not f.path.lower().endswith(".zip"):
            out.append(f)
            continue
        base = PurePosixPath(f.path).stem or "kg"
        with zipfile.ZipFile(io.BytesIO(f.data)) as z:
            for info in z.infolist():
                inner = PurePosixPath(info.filename)
                if info.is_dir() or "__MACOSX" in inner.parts or inner.name.startswith("."):
                    continue
                rel = f"{base}/{inner}" if inner.parts[0] == "fact_classes" or len(inner.parts) == 1 else str(inner)
                out.append(RdfFile(rel, z.read(info)))
    return out


def _place(path: str) -> tuple[str | None, str | None, str]:
    """-> (kg, cube folder, file name) from a relative path."""
    parts = PurePosixPath(path).parts
    name = parts[-1]
    if "fact_classes" in parts[:-1]:
        i = parts.index("fact_classes")
        cube = parts[i + 1] if i + 1 < len(parts) - 1 else None
        kg = parts[i - 1] if i > 0 else (cube.rsplit("_", 1)[0] if cube else None)
        return (slug(kg) if kg else None), cube, name
    if len(parts) >= 3 and name.startswith("mdkg_"):  # <kg>/<cube>/mdkg_*.ttl without the fact_classes level
        return slug(parts[-3]), parts[-2], name
    if len(parts) == 2 and name.startswith("mdkg_"):  # <cube>/mdkg_*.ttl: name the KG after the cube's fact class
        return slug(parts[0].rsplit("_", 1)[0]) or None, parts[0], name
    kg = slug(parts[-2]) if len(parts) > 1 else None
    return kg, None, name


def read_mdkgs(files: list[RdfFile]) -> tuple[dict[str, Mdkg], list[tuple[str, Graph]]]:
    """-> ({kg: Mdkg}, [(path, identity graph)])."""
    mdkgs: dict[str, Mdkg] = {}
    identity: list[tuple[str, Graph]] = []
    cubes: dict[tuple[str, str], dict[str, RdfFile]] = {}
    for f in _expand(files):
        kg, cube, name = _place(f.path)
        if name == "mdkg_dataset.nq" and kg is None:  # a bare bundle: name the KG after its fact class later
            kg, cube = "", f.path
        if cube is not None and name in ("mdkg_dataset.nq", "mdkg_schema.ttl", "mdkg_data.ttl"):
            cubes.setdefault((kg, cube), {})[name] = f
            continue
        if name == "factclass_selection.json" and kg:
            m = mdkgs.setdefault(kg, Mdkg(kg))
            m.selection = json.loads(f.data.decode("utf-8"))
            m.files.append(f.path)
            m.raw[f.path] = f.data
            continue
        if name == "kg2md.log" and kg:
            m = mdkgs.setdefault(kg, Mdkg(kg))
            m.raw[f.path] = f.data
            continue
        if f.fmt is None:
            continue
        g = parse(f)
        if not len(g):  # e.g. an empty identity.ttl
            continue
        if is_identity_graph(g):
            identity.append((f.path, g))
        else:
            raise ValueError(f"{f.path} {HINT}")
    for (kg, cube), parts in sorted(cubes.items()):
        if "mdkg_dataset.nq" in parts:
            f = parts["mdkg_dataset.nq"]
            ds = Dataset()
            ds.parse(data=f.data.decode("utf-8"), format="nquads")
            graphs = {c.identifier: c for c in ds.graphs()}
            source, schema, data = (graphs.get(i, Graph()) for i in (SOURCE_GRAPH, SCHEMA_GRAPH, CUBE_GRAPH))
            used = [f]
        elif {"mdkg_schema.ttl", "mdkg_data.ttl"} <= parts.keys():
            source = Graph()
            schema, data = parse(parts["mdkg_schema.ttl"]), parse(parts["mdkg_data.ttl"])
            used = [parts["mdkg_schema.ttl"], parts["mdkg_data.ttl"]]
        else:
            raise ValueError(f"{', '.join(p.path for p in parts.values())}: a cube folder needs mdkg_dataset.nq, "
                             "or both mdkg_schema.ttl and mdkg_data.ttl.")
        if (None, RDF.type, QB_DATASET) not in data:
            raise ValueError(f"{used[0].path} {HINT}")
        if not kg:  # bare bundle: the dataset IRI ends in <FactClass>_Dataset
            ds_iri = str(next(data.subjects(RDF.type, QB_DATASET)))
            kg = slug(ds_iri.rsplit("/", 1)[-1].removesuffix("_Dataset")) or "mdkg"
        m = mdkgs.setdefault(kg, Mdkg(kg))
        for target, g in ((m.source, source), (m.schema, schema), (m.data, data)):
            for t in g:
                target.add(t)
            for prefix, ns in g.namespaces():
                target.bind(prefix, ns, override=False)
        m.cubes.append(PurePosixPath(cube).name if cube else cube)
        for p in used:
            m.files.append(p.path)
            m.raw[p.path] = p.data
        for name, p in parts.items():
            m.raw.setdefault(p.path, p.data)
    for kg, m in list(mdkgs.items()):
        if not m.cubes:
            raise ValueError(f"{', '.join(m.files) or kg} {HINT}")
    return mdkgs, identity


def with_member_descriptions(data: Graph, source: Graph) -> Graph:
    """The cube graph plus the literal descriptions (labels, names, codes) its level members have in the
    source graph, so queries can show member names and linking can compare them. The saved files are not changed."""
    out = Graph()
    for t in data:
        out.add(t)
    for prefix, ns in data.namespaces():
        out.bind(prefix, ns, override=False)
    if len(source):
        for member in set(data.subjects(QB4O_MEMBER_OF, None)):
            for p, o in source.predicate_objects(member):
                if isinstance(o, Literal):
                    out.add((member, p, o))
    return out
