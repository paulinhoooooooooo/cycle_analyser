#!/usr/bin/env python3
"""
Logiciel d'Analyse de Cycles de Marché
Usage : python main.py <TICKER> [options]
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()

PHASE_STYLE = {
    "bullish": ("[green]▲ Haussier[/green]", "green"),
    "bearish": ("[red]▼ Baissier[/red]", "red"),
    "peak": ("[yellow]◈ Sommet[/yellow]", "yellow"),
    "trough": ("[yellow]◇ Creux[/yellow]", "yellow"),
}


def print_banner() -> None:
    console.print(Panel.fit(
        "[bold cyan]Analyseur de Cycles de Marché[/bold cyan]\n"
        "[dim]Détection par FFT • Combinaisons optimales • Rapport HTML[/dim]",
        border_style="cyan",
    ))
    console.print()


def print_cycle_table(cycles: list, title: str = "Cycles Détectés") -> None:
    table = Table(title=title, box=box.ROUNDED, border_style="dim", show_lines=False)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Longueur", justify="center", style="bold cyan")
    table.add_column("Amplitude", justify="right")
    table.add_column("Force", justify="right")
    table.add_column("Stabilité", justify="right")
    table.add_column("R²", justify="right")
    table.add_column("Phase actuelle", justify="left")

    for c in cycles:
        phase_str, _ = PHASE_STYLE.get(c.phase_state, ("—", "white"))
        stab_str = f"[bold green]{c.stability:.2f}[/bold green]" if c.stability >= 0.5 else f"{c.stability:.2f}"
        table.add_row(
            str(c.rank),
            str(c.period),
            f"{c.amplitude:,.2f}",
            f"{c.strength:.2f}",
            stab_str,
            f"{c.r_squared:.3f}",
            phase_str,
        )

    console.print(table)


def print_combinations(combinations: dict) -> None:
    for size, label in [(2, "Top 3 — Combinaisons de 2 cycles"), (3, "Top 3 — Combinaisons de 3 cycles")]:
        combo_list = combinations.get(size, [])
        if not combo_list:
            continue
        table = Table(title=label, box=box.ROUNDED, border_style="dim")
        table.add_column("Rang", justify="right", style="dim")
        table.add_column("Cycles (barres)", style="bold")
        table.add_column("Haussier (total)", justify="right")
        table.add_column("Réussite", justify="right")
        table.add_column("Baissier (total)", justify="right")
        table.add_column("Zones ↑", justify="right")

        for i, combo in enumerate(combo_list, 1):
            col_b = "green" if combo.total_return_pct >= 0 else "red"
            bear_col = "red" if combo.bearish_total_return_pct <= 0 else "green"
            hr_col = "green" if combo.hit_rate >= 60 else ("yellow" if combo.hit_rate >= 45 else "red")
            table.add_row(
                f"#{i}",
                combo.label,
                f"[{col_b}]{combo.total_return_pct:+.1f}%[/{col_b}]",
                f"[{hr_col}]{combo.hit_rate:.0f}%[/{hr_col}]",
                f"[{bear_col}]{combo.bearish_total_return_pct:+.1f}%[/{bear_col}]",
                str(combo.n_zones),
            )
        console.print(table)
        console.print()


def interactive_mode(prices, dates, cycles, ticker, output_dir: Path) -> None:
    """Let user pick cycles and generate a custom combination chart."""
    from cycle_analyzer.combination_analyzer import get_custom_combination
    from cycle_analyzer.visualizer import plot_combination, fig_to_base64
    from cycle_analyzer.report_generator import generate_report

    console.print("\n[bold cyan]Mode interactif — Sélection personnalisée de cycles[/bold cyan]")
    console.print("[dim]Entrez les numéros des cycles (ex: 1 3 5) ou 'q' pour quitter[/dim]\n")

    while True:
        try:
            raw = console.input("[bold]> Sélection (rangs séparés par espaces) : [/bold]").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if raw.lower() in ("q", "quit", "exit", ""):
            break

        try:
            selected_ranks = [int(x) for x in raw.split()]
        except ValueError:
            console.print("[red]Entrée invalide. Utilisez des numéros séparés par des espaces.[/red]")
            continue

        selected = [c for c in cycles if c.rank in selected_ranks]
        if len(selected) < 2:
            console.print("[yellow]Sélectionnez au moins 2 cycles.[/yellow]")
            continue

        console.print(f"[dim]Calcul de la combinaison : {', '.join(str(c.period) for c in selected)}...[/dim]")
        combo = get_custom_combination(prices, selected)

        console.print(
            f"\n[bold]Résultat :[/bold] "
            f"Rendement total [{'green' if combo.total_return_pct >= 0 else 'red'}]{combo.total_return_pct:+.1f}%[/]  "
            f"Réussite {combo.hit_rate:.0f}%  "
            f"{combo.n_zones} zones"
        )

        fig = plot_combination(prices, dates, combo, ticker)
        out_path = output_dir / f"combo_custom_{'_'.join(str(p) for p in combo.periods)}.png"
        fig.savefig(out_path, dpi=130, bbox_inches="tight", facecolor="#0d1117")
        import matplotlib.pyplot as plt
        plt.close(fig)
        console.print(f"[green]Graphique sauvegardé : {out_path}[/green]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse les cycles de marché d'un actif financier.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python main.py SPY
  python main.py ^FCHI --period 3y --interval 1d
  python main.py AAPL --period 5y --interval 1wk --cycles 20
  python main.py BTC-USD --period 1y --no-browser
        """,
    )
    parser.add_argument("ticker", help="Symbole boursier (ex: SPY, ^FCHI, AAPL) ou chemin vers un fichier CSV local")
    parser.add_argument("--period", default="3y",
                        help="Période de données (1y 2y 3y 5y max …) [défaut: 3y]")
    parser.add_argument("--interval", default="1d",
                        help="Intervalle de bougie (1d 1wk 1mo) [défaut: 1d]")
    parser.add_argument("--cycles", type=int, default=20,
                        help="Nombre maximum de cycles à détecter [défaut: 20]")
    parser.add_argument("--min-period", type=int, default=10,
                        help="Période minimale en barres [défaut: 10]")
    parser.add_argument("--max-period", type=int, default=None,
                        help="Période maximale en barres [défaut: N/2]")
    parser.add_argument("--output", default=None,
                        help="Chemin du rapport HTML de sortie")
    parser.add_argument("--no-browser", action="store_true",
                        help="Ne pas ouvrir le navigateur automatiquement")
    parser.add_argument("--interactive", action="store_true",
                        help="Mode interactif pour sélectionner des cycles manuellement")
    parser.add_argument("--select", default=None,
                        help="Sélectionner des périodes spécifiques séparées par des virgules "
                             "(ex: 63,21,126). Génère un graphique de combinaison directement.")
    parser.add_argument("--pinescript", default=None,
                        help="Générer un script TradingView Pine Script v6 pour les cycles donnés "
                             "(ex: 81,21 ou 81,42,21). Sauvegarde un fichier .pine et affiche "
                             "les valeurs 'ago' calculées par analyse FFT.")
    args = parser.parse_args()

    print_banner()

    # ── Imports ───────────────────────────────────────────────────────────────
    try:
        from cycle_analyzer.data_fetcher import fetch_data, get_ticker_info, get_close_prices, get_dates
        from cycle_analyzer.cycle_detector import detect_cycles
        from cycle_analyzer.combination_analyzer import analyze_combinations
        from cycle_analyzer.report_generator import generate_report
    except ImportError as e:
        console.print(f"[red]Erreur d'import : {e}[/red]")
        console.print("[yellow]Installez les dépendances : pip install -r requirements.txt[/yellow]")
        sys.exit(1)

    ticker = args.ticker.upper()

    # ── Fetch data (always needed) ────────────────────────────────────────────
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        from pathlib import Path as _Path
        is_csv = _Path(args.ticker).exists() and args.ticker.lower().endswith((".csv", ".txt"))

        if is_csv:
            t1 = progress.add_task(f"Chargement du fichier {args.ticker}…", total=None)
            try:
                from cycle_analyzer.data_fetcher import load_from_csv
                data = load_from_csv(args.ticker)
                ticker = _Path(args.ticker).stem.upper()
            except ValueError as e:
                progress.stop()
                console.print(f"[red]Erreur : {e}[/red]")
                sys.exit(1)
        else:
            t1 = progress.add_task(f"Téléchargement des données pour {ticker}…", total=None)
            try:
                data = fetch_data(ticker, period=args.period, interval=args.interval)
            except ValueError as e:
                progress.stop()
                console.print(f"[red]Erreur : {e}[/red]")
                sys.exit(1)

        progress.update(t1, description=f"[green]✓[/green] {len(data)} barres chargées")

    prices = get_close_prices(data)
    dates = get_dates(data)

    # ── Fast path: --select bypasses full analysis ────────────────────────────
    if args.select:
        import numpy as np
        import matplotlib.pyplot as plt
        import warnings
        from cycle_analyzer.cycle_detector import CycleInfo, _detrend_log, _fit_sine, _phase_state
        from cycle_analyzer.combination_analyzer import get_custom_combination
        from cycle_analyzer.visualizer import plot_combination

        try:
            sel_periods = [int(p.strip()) for p in args.select.split(",")]
        except ValueError:
            console.print("[red]--select : format invalide. Utilisez des entiers séparés par des virgules (ex: 63,21,126)[/red]")
            sys.exit(1)

        detrended_g, trend_g = _detrend_log(prices)

        sel_cycles = []
        for sp in sel_periods:
            A_s, B_s, amp_s = _fit_sine(detrended_g, float(sp))
            state_s, osc_s, dir_s = _phase_state(A_s, B_s, float(sp), len(prices) - 1)
            t_arr = np.arange(len(prices), dtype=float)
            osc_arr = np.exp(trend_g) * (
                1 + A_s * np.cos(2 * np.pi * t_arr / sp)
                + B_s * np.sin(2 * np.pi * t_arr / sp)
            )
            synth = CycleInfo(
                period=sp, period_exact=float(sp),
                amplitude=round(amp_s * prices[-1], 2), strength=1.0, stability=0.0,
                phase_state=state_s, current_value=osc_s, current_direction=dir_s,
                oscillator=osc_arr,
                r_squared=0.0, amplitude_log=amp_s, coeff_a=A_s, coeff_b=B_s,
            )
            sel_cycles.append(synth)

        combo = get_custom_combination(prices, sel_cycles)
        console.print(f"\n[bold]Combinaison {combo.label}[/bold]")
        console.print(
            f"  Rendement total : [{'green' if combo.total_return_pct >= 0 else 'red'}]{combo.total_return_pct:+.1f}%[/]  "
            f"| Réussite : {combo.hit_rate:.0f}%  | {combo.n_zones} zones"
        )

        out_select = Path(f"selection_{'_'.join(str(p) for p in sel_periods)}.png")
        fig = plot_combination(prices, dates, combo, ticker)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fig.savefig(out_select, dpi=130, bbox_inches="tight", facecolor="#0d1117")
        plt.close(fig)
        console.print(f"[green]Graphique sauvegardé : {out_select.resolve()}[/green]")

        if not args.no_browser:
            try:
                import subprocess, platform
                if platform.system() == "Darwin":
                    subprocess.run(["open", str(out_select)], check=False)
                else:
                    webbrowser.open(out_select.resolve().as_uri())
            except Exception:
                pass

        console.print("\n[dim]Analyse terminée.[/dim]")
        return

    # ── Fast path: --pinescript ───────────────────────────────────────────────
    if args.pinescript:
        import math as _math
        import numpy as np
        from cycle_analyzer.cycle_detector import _detrend_log, _fit_sine
        from cycle_analyzer.pinescript_generator import generate_pinescript

        try:
            pine_periods = [int(p.strip()) for p in args.pinescript.split(",")]
        except ValueError:
            console.print("[red]--pinescript : format invalide. Utilisez des entiers séparés par des virgules (ex: 81,21)[/red]")
            sys.exit(1)

        if not (1 <= len(pine_periods) <= 3):
            console.print("[red]--pinescript : indiquez 1, 2 ou 3 cycles (ex: 165 ou 81,21 ou 81,42,21)[/red]")
            sys.exit(1)

        N = len(prices)
        detrended_g, _ = _detrend_log(prices)

        console.print()
        ago_values = []
        coeff_table = []
        for sp in pine_periods:
            A_s, B_s, amp_s = _fit_sine(detrended_g, float(sp))
            psi = _math.atan2(A_s, B_s)
            ago = int(round(((N - 1) + psi * float(sp) / (2 * _math.pi)) % float(sp)))
            ago_values.append(ago)
            coeff_table.append((sp, A_s, B_s, amp_s, psi, ago))

        # Print computed parameters
        from rich.table import Table as _Table
        ptable = _Table(title="Paramètres Pine Script calculés", box=box.ROUNDED, border_style="cyan")
        ptable.add_column("Cycle (barres)", justify="center", style="bold cyan")
        ptable.add_column("A (cos)", justify="right")
        ptable.add_column("B (sin)", justify="right")
        ptable.add_column("ψ = atan2(A,B)", justify="right")
        ptable.add_column("ago (calculé)", justify="center", style="bold yellow")
        for sp, A_s, B_s, amp_s, psi, ago in coeff_table:
            ptable.add_row(str(sp), f"{A_s:.4f}", f"{B_s:.4f}", f"{_math.degrees(psi):.1f}°", str(ago))
        console.print(ptable)

        script = generate_pinescript(ticker, pine_periods, ago_values)

        out_pine = Path(f"cycles_{ticker}_{'_'.join(str(p) for p in pine_periods)}.pine")
        out_pine.write_text(script, encoding="utf-8")

        console.print(Panel(
            f"[bold green]Script Pine sauvegardé :[/bold green] {out_pine.resolve()}\n\n"
            "[dim]Ouvrez ce fichier, sélectionnez tout (Ctrl+A) et copiez (Ctrl+C),\n"
            "puis collez dans TradingView → Pine Editor → Nouveau script.[/dim]",
            border_style="green", expand=False,
        ))

        # Open file in default editor and copy to clipboard
        try:
            import subprocess as _sp, platform as _plat
            _sys = _plat.system()
            if _sys == "Windows":
                _sp.Popen(["notepad.exe", str(out_pine)])
                console.print("[dim]✓ Fichier ouvert dans le Bloc-notes[/dim]")
                # Copy to clipboard via PowerShell Set-Clipboard (most reliable on Windows)
                ps_cmd = f'Set-Clipboard -Value (Get-Content -Path "{out_pine.resolve()}" -Raw)'
                _sp.run(["powershell", "-Command", ps_cmd], check=False)
                console.print("[dim]✓ Copié dans le presse-papiers (Ctrl+V pour coller)[/dim]")
            elif _sys == "Darwin":
                _sp.Popen(["open", str(out_pine)])
                _sp.run(["pbcopy"], input=script.encode("utf-8"), check=False)
                console.print("[dim]✓ Fichier ouvert et copié dans le presse-papiers[/dim]")
        except Exception:
            pass

        console.print("\n[dim]Analyse terminée.[/dim]")
        return

    # ── Full analysis pipeline ────────────────────────────────────────────────
    ticker_info = get_ticker_info(ticker) if not is_csv else {"name": ticker, "currency": "", "exchange": "", "type": ""}

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:

        t2 = progress.add_task("Détection des cycles par FFT…", total=None)
        cycles = detect_cycles(
            prices,
            min_period=args.min_period,
            max_period=args.max_period,
            n_cycles=args.cycles,
        )
        progress.update(t2, description=f"[green]✓[/green] {len(cycles)} cycles détectés")
        progress.stop_task(t2)

        t3 = progress.add_task("Analyse des combinaisons de cycles…", total=None)
        combinations = analyze_combinations(prices, cycles, top_n_per_size=3)
        n_found = sum(len(v) for v in combinations.values())
        progress.update(t3, description=f"[green]✓[/green] {n_found} meilleures combinaisons trouvées")
        progress.stop_task(t3)

        t4 = progress.add_task("Génération du rapport HTML…", total=None)
        html = generate_report(
            ticker=ticker,
            ticker_info=ticker_info,
            prices=prices,
            dates=dates,
            cycles=cycles,
            combinations=combinations,
            period=args.period,
            interval=args.interval,
        )
        progress.update(t4, description="[green]✓[/green] Rapport généré")
        progress.stop_task(t4)

    if args.output:
        report_path = Path(args.output)
    else:
        report_path = Path(f"rapport_{ticker}_{args.period}.html")

    report_path.write_text(html, encoding="utf-8")

    console.print()
    print_cycle_table(cycles)
    console.print()
    print_combinations(combinations)
    console.print()

    console.print(
        Panel(
            f"[bold green]Rapport sauvegardé :[/bold green] {report_path.resolve()}",
            border_style="green",
            expand=False,
        )
    )

    if not args.no_browser:
        try:
            webbrowser.open(report_path.resolve().as_uri())
        except Exception:
            pass

    if args.interactive or sys.stdin.isatty():
        try:
            answer = console.input("\n[bold]Voulez-vous sélectionner des cycles manuellement ? (o/N) : [/bold]").strip().lower()
            if answer in ("o", "oui", "y", "yes"):
                print_cycle_table(cycles, title="Cycles disponibles — entrez les rangs (#)")
                interactive_mode(prices, dates, cycles, ticker, report_path.parent)
        except (EOFError, KeyboardInterrupt):
            pass

    console.print("\n[dim]Analyse terminée.[/dim]")


if __name__ == "__main__":
    main()
