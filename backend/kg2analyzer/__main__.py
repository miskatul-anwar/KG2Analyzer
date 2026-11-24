"""Command line: uv run kg2analyzer {build,serve,ask,sync-notebook}.

KG inputs (``build``, ``serve --kgs``, ``ask --kgs``) are any mix of RDF files, TBox/ABox pairs
(``x_tbox.ttl`` + ``x_abox.ttl``), one folder per KG, zip archives and owl:sameAs files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _kg_args(p: argparse.ArgumentParser, required: bool) -> None:
    p.add_argument("--kgs" if not required else "kgs", nargs="+" if required else "*", metavar="PATH",
                   help="KG files, folders or zips")
    p.add_argument("--no-link", action="store_true", help="do not discover owl:sameAs links between the KGs")
    p.add_argument("--threshold", type=float, default=0.6, help="auto-link score threshold (default 0.6)")
    p.add_argument("--max-facts", type=int, help="cap the fact cubes per KG (built-in engine only)")
    p.add_argument("--decider", choices=["tev1", "structural"],
                   help="who answers KG2MD's questions: tev1 (default, needs `uv sync --extra tev1`) or the "
                        "structural stand-in (not Tev1; for machines without PyTorch)")


def _summary(rep: dict) -> str:
    lines = [f"{'KG':<14}{'triples':>9}  {'tau*':>8}  fact cubes (observations, measures)"]
    for k in rep["kgs"]:
        cubes = ", ".join(f"{c['fact_class']} ({c['observations']}, {c['measures']})" for c in k["cubes"]) or "-"
        tau = "-" if k["otsu_threshold"] is None else k["otsu_threshold"]
        lines.append(f"{k['kg']:<14}{k['triples']:>9}  {tau:>8}  {cubes}")
        for w in k.get("warnings", []):
            lines.append(f"{'':<14}note: {w}")
    i = rep["identity"]
    lines.append(f"identity: {i['supplied_links']} supplied + {i['links_added']} discovered links "
                 f"-> {i['clusters']} entity clusters; {rep['named_graphs']} named graphs; {rep['seconds']['total']}s")
    return "\n".join(lines)


def _mdkg_paths(paths: list[str]) -> list:
    """Saved MDKG folders; a folder that is one KG's output (it holds fact_classes/) keeps its name as the KG."""
    from kg2analyzer.ingest import RdfFile, read_paths

    out = []
    for p in map(Path, paths):
        if p.is_dir() and (p / "fact_classes").is_dir():
            out += [RdfFile(f"{p.resolve().name}/{f.path}", f.data) for f in read_paths([p])]
        else:
            out += read_paths([p])
    return out


def _build(paths, args):
    import os

    from kg2analyzer.analyzer import KG2Analyzer

    if getattr(args, "decider", None):
        os.environ["KG2A_DECIDER"] = args.decider
    az = KG2Analyzer()
    rep = az.ingest_paths(paths, auto_link=not args.no_link, link_threshold=args.threshold, max_facts=args.max_facts)
    print(_summary(rep), file=sys.stderr)
    return az, rep


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kg2analyzer", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="KGs -> one MDKG per KG + identity graph, written to a folder")
    _kg_args(b, required=True)
    b.add_argument("--out", default="mdkg", help="output folder (default ./mdkg)")

    s = sub.add_parser("serve", help="start the web UI + API")
    _kg_args(s, required=False)
    s.add_argument("--mdkgs", nargs="*", metavar="PATH", help="saved MDKG files/folders/zips to preload into Query and Ask")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    a = sub.add_parser("ask", help="ask one question over saved MDKGs (--mdkgs) or raw KGs (--kgs)")
    a.add_argument("question")
    _kg_args(a, required=False)
    a.add_argument("--mdkgs", nargs="*", metavar="PATH", help="saved MDKG files/folders/zips")
    n = sub.add_parser("sync-notebook", help="replace the bundled KG2MD notebook with a newer copy")
    n.add_argument("notebook", help="path to KG2MD_ML_Explainable_Otsu_MultiFact.ipynb")
    args = p.parse_args(argv)

    if args.cmd == "build":
        az, rep = _build(args.kgs, args)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for rel, data in az.mdkg_files().items():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_bytes(data)
        (out / "identity.ttl").write_text(az.store.identity.serialize(format="turtle"))
        (out / "report.json").write_text(json.dumps(rep, indent=2, default=str))
        print(f"wrote {len(rep['kgs'])} MDKG folder(s), identity.ttl and report.json to {out}/", file=sys.stderr)
    elif args.cmd == "sync-notebook":
        from kg2analyzer.kg2md.notebook import NOTEBOOK, code_cells

        src = Path(args.notebook)
        cells = code_cells(src)
        if not any("class Tev1FactDecider" in c for _, c in cells) or not any("generate_mdkg_for_fact" in c for _, c in cells):
            p.error(f"{src} does not look like the KG2MD notebook")
        NOTEBOOK.write_bytes(src.read_bytes())
        print(f"bundled {src} ({len(cells)} code cells) as {NOTEBOOK}", file=sys.stderr)
    elif args.cmd == "serve":
        import uvicorn

        import os

        if args.decider:
            os.environ["KG2A_DECIDER"] = args.decider
        from kg2analyzer import server

        if args.kgs:  # raw KGs -> the Build section
            server.WORKSPACES["build"].ingest_paths(args.kgs, auto_link=not args.no_link, link_threshold=args.threshold,
                                                    max_facts=args.max_facts)
            print(_summary(server.WORKSPACES["build"].last_report), file=sys.stderr)
        if args.mdkgs:  # saved MDKGs -> the Query and Ask sections
            for ws in ("query", "ask"):
                rep = server.WORKSPACES[ws].load_mdkgs(_mdkg_paths(args.mdkgs), auto_link=not args.no_link,
                                                       link_threshold=args.threshold)
            print(f"loaded {len(rep['mdkgs'])} MDKG(s) into Query and Ask", file=sys.stderr)
        uvicorn.run(server.app, host=args.host, port=args.port)
    elif args.cmd == "ask":
        if args.mdkgs:
            from kg2analyzer.analyzer import KG2Analyzer

            az = KG2Analyzer()
            az.load_mdkgs(_mdkg_paths(args.mdkgs), auto_link=not args.no_link, link_threshold=args.threshold)
        elif args.kgs:
            az, _ = _build(args.kgs, args)
        else:
            p.error("ask needs --mdkgs PATH [PATH ...] (or --kgs to build first)")
        print(json.dumps(az.ask(args.question).to_dict(), indent=1, default=str))


if __name__ == "__main__":
    main()
