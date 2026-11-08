"""Ligne de commande : ``docparse run`` et ``docparse eval``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import pipeline
from .evaluate import FIELDS, evaluate, wilson


def pct(x: float, digits: int = 0) -> str:
    return "—" if x != x else f"{x * 100:.{digits}f}".replace(".", ",") + " %"


def table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = lambda cells: "  " + "   ".join(c.ljust(widths[i]) if i < 2 else c.rjust(widths[i]) for i, c in enumerate(cells))
    return "\n".join([line(headers), "  " + "───".join("─" * w for w in widths), *map(line, rows)])


def _suppliers(args: argparse.Namespace):
    """Liste des fournisseurs connus : None si non demandée, False si le fichier est introuvable."""
    if not args.suppliers:
        return None
    path = Path(args.suppliers)
    if not path.is_file():
        print(f"Introuvable : {path}", file=sys.stderr)
        return False
    return pipeline.load_suppliers(path)


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"Introuvable : {root}", file=sys.stderr)
        return 1
    suppliers = _suppliers(args)
    if suppliers is False:
        return 1
    results = pipeline.process(root, known_suppliers=suppliers)
    if not results:
        print(f"Aucun document .pdf ou .txt dans {root}", file=sys.stderr)
        return 1
    rows = [[r.source, r.invoice.number or "—", f"{r.invoice.total:.2f}" if r.invoice.total is not None else "—", "OUI" if r.needs_review else "non"] for r in results]
    print(table(["Fichier", "Numéro", "Total", "À vérifier"], rows))
    flagged = sum(r.needs_review for r in results)
    print(f"\n{len(results)} document(s) lu(s), {flagged} à vérifier à la main.")
    if args.out:
        pipeline.write_csv(results, Path(args.out), args.delimiter)
        print(f"Résultats écrits dans {args.out} (colonne « problemes » : le détail).")
    print("Rappel : un document non signalé n'est pas garanti juste ; voir « docparse eval » pour mesurer les erreurs silencieuses.")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    root, truth_path = Path(args.path), Path(args.truth)
    for path in (root, truth_path):
        if not path.exists():
            print(f"Introuvable : {path}", file=sys.stderr)
            return 1
    truth = json.loads(truth_path.read_text(encoding="utf-8"))["files"]
    suppliers = _suppliers(args)
    if suppliers is False:
        return 1
    ev = evaluate(pipeline.process(root, known_suppliers=suppliers), truth)
    if ev.documents == 0:
        print("Aucun document commun entre le dossier et le fichier de vérité.", file=sys.stderr)
        return 1
    print(f"Évaluation sur {ev.documents} documents (intervalles de Wilson à 95 %)\n")
    rows = []
    for name in FIELDS:
        k = ev.field_correct[name]
        lo, hi = wilson(k, ev.documents)
        rows.append([name, f"{k}/{ev.documents}", pct(k / ev.documents), f"[{pct(lo)} ; {pct(hi)}]"])
    print(table(["Champ", "Justes", "Taux", "IC 95 %"], rows))
    o = ev.overall
    lo, hi = wilson(o.fully_correct, o.documents)
    print(f"\nDocuments entièrement justes : {o.fully_correct}/{o.documents} ({pct(o.fully_correct / o.documents)}, IC [{pct(lo)} ; {pct(hi)}])")
    if o.wrong:
        print(f"Documents faux : {o.wrong}, dont {o.flagged_wrong} signalés « à vérifier » et {o.silent_errors} ERREURS SILENCIEUSES")
    print(f"Fausses alertes (justes mais signalés) : {o.false_alarms}")
    print("\nPar mise en page :")
    print(table(["Modèle", "Docs", "Justes", "Faux signalés", "Silencieuses"],
                [[t, str(g.documents), str(g.fully_correct), str(g.flagged_wrong), str(g.silent_errors)] for t, g in ev.by_template.items()]))
    if ev.silent_error_files:
        print("\nErreurs silencieuses : " + ", ".join(ev.silent_error_files))
    if ev.not_in_truth or ev.not_processed:
        print(f"\nIgnorés : {len(ev.not_in_truth)} document(s) sans vérité, {len(ev.not_processed)} vérité(s) sans document.")
    print("\nLimite : sur des documents fictifs, ces chiffres mesurent la méthode, pas la performance sur de vrais documents.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docparse", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Lit un dossier (ou un fichier) de factures et contrôle chaque résultat")
    r.add_argument("path")
    r.add_argument("--out", help="Écrit un CSV (lisible par Excel)")
    r.add_argument("--delimiter", default=",", help="Séparateur du CSV (« ; » pour Excel en français)")
    r.add_argument("--suppliers", help="Fichier texte, un fournisseur par ligne : un nom absent de la liste est signalé")
    r.set_defaults(func=cmd_run)
    e = sub.add_parser("eval", help="Compare les résultats à une vérité connue et compte les erreurs silencieuses")
    e.add_argument("path")
    e.add_argument("--truth", required=True)
    e.add_argument("--suppliers", help="Fichier texte, un fournisseur par ligne : un nom absent de la liste est signalé")
    e.set_defaults(func=cmd_eval)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
