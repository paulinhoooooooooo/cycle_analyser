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


def _run_sl_simulation(console, prices, dates, combo, sl_pct: float, ticker: str,
                       out_filename: str, no_browser: bool, fixed: bool = False) -> None:
    """Generate the SL simulation chart and print a summary panel."""
    import warnings as _w
    import matplotlib.pyplot as _plt
    from cycle_analyzer.combination_analyzer import simulate_sl_zones, simulate_sl_zones_fixed
    from cycle_analyzer.visualizer import plot_sl_simulation

    sl_results = (simulate_sl_zones_fixed if fixed else simulate_sl_zones)(prices, combo.zones, sl_pct)
    sl_compound = 1.0
    sl_simple = 0.0
    n_hits = 0
    for r in sl_results:
        sl_compound *= 1 + r.sl_return_pct / 100
        sl_simple += r.sl_return_pct
        if r.sl_hit:
            n_hits += 1
    sl_total = round((sl_compound - 1) * 100, 2)
    sl_simple = round(sl_simple, 2)
    no_sl_simple = combo.total_return_pct

    sl_mode = "fixe" if fixed else "suiveur"
    fig_sl = plot_sl_simulation(prices, dates, combo, sl_results, sl_pct, ticker, sl_mode=sl_mode)
    out_sl = Path(out_filename)
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        fig_sl.savefig(out_sl, dpi=130, bbox_inches="tight", facecolor="#0d1117")
    _plt.close(fig_sl)

    col_c = "green" if sl_total >= 0 else "red"
    col_s = "green" if sl_simple >= 0 else "red"
    diff_c = round(sl_total - combo.compound_return_pct, 2)
    diff_s = round(sl_simple - no_sl_simple, 2)
    diff_col_c = "green" if diff_c >= 0 else "red"
    diff_col_s = "green" if diff_s >= 0 else "red"
    console.print(Panel(
        f"[bold cyan]Simulation Stop-Loss {sl_pct}% ({'fixe' if fixed else 'suiveur'})[/bold cyan]\n"
        f"  Avec SL  — composé : [{col_c}]{sl_total:+.1f}%[/{col_c}]   simple : [{col_s}]{sl_simple:+.1f}%[/{col_s}]\n"
        f"  Sans SL  — composé : {combo.compound_return_pct:+.1f}%   simple : {no_sl_simple:+.1f}%\n"
        f"  Différence composé : [{diff_col_c}]{diff_c:+.1f}%[/{diff_col_c}]   "
        f"simple : [{diff_col_s}]{diff_s:+.1f}%[/{diff_col_s}]\n"
        f"  SL déclenchés      : {n_hits} / {len(sl_results)} zones\n"
        f"  Graphique SL       : {out_sl.resolve()}",
        border_style="cyan", expand=False,
    ))

    try:
        import subprocess as _sp, platform as _plat
        _sys = _plat.system()
        if not no_browser:
            if _sys == "Windows":
                _sp.Popen(["explorer", str(out_sl.resolve())])
            elif _sys == "Darwin":
                _sp.Popen(["open", str(out_sl)])
            else:
                import webbrowser as _wb
                _wb.open(out_sl.resolve().as_uri())
    except Exception:
        pass


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
                        help="Période de données GLISSANTE (1y 2y 3y 5y max …) [défaut: 3y]. "
                             "Le début recule chaque jour → les résultats évoluent avec le temps.")
    parser.add_argument("--start", default=None, metavar="AAAA-MM-JJ",
                        help="Date de début FIXE (ex: --start 2021-01-01). Le passé est figé : "
                             "le début ne bouge jamais, seules les nouvelles barres s'ajoutent. "
                             "Rend les cycles/rendements reproductibles. Ignore --period si fourni.")
    parser.add_argument("--recent", nargs="?", type=float, const=0.0, default=None,
                        metavar="DEMIVIE",
                        help="Priorité au RÉCENT : privilégie les cycles/combinaisons qui "
                             "performent ces derniers mois plutôt qu'au début de la période. "
                             "Optionnel : demi-vie en barres (ex: --recent 250). Sans valeur, "
                             "demi-vie = 1/4 de la période analysée.")
    parser.add_argument("--reussite", nargs="?", type=float, const=80.0, default=None,
                        metavar="MIN",
                        help="Favoriser la RÉUSSITE : n'affiche que les combinaisons dont le "
                             "taux de réussite est >= MIN%% (défaut 80%% si aucune valeur). "
                             "Ex: --reussite ou --reussite 85.")
    parser.add_argument("--zone", type=int, default=None, metavar="MIN",
                        help="Nombre MINIMUM de zones par combinaison (ex: --zone 15). "
                             "Long: zones haussières, Short: zones baissières. Plus de zones "
                             "= statistique plus fiable, mais exclut les cycles très longs.")
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
    parser.add_argument("--SL", type=float, default=None, metavar="PCT",
                        help="Simuler un stop-loss suiveur de X%% sur les zones haussières "
                             "(ex: --SL 5). Génère un graphique de comparaison avec/sans SL.")
    parser.add_argument("--SLf", type=float, default=None, metavar="PCT",
                        help="Simuler un stop-loss FIXE de X%% sous le prix d'entrée. "
                             "Le SL ne bouge pas même si le prix monte (ex: --SLf 5).")
    args = parser.parse_args()
    # Consolidate: if --SLf given, treat as --SL in fixed mode
    _sl_fixed_mode = args.SLf is not None
    if _sl_fixed_mode and args.SL is None:
        args.SL = args.SLf

    print_banner()

    # ── Imports ───────────────────────────────────────────────────────────────
    try:
        from cycle_analyzer.data_fetcher import fetch_data, get_ticker_info, get_close_prices, get_dates
        from cycle_analyzer.cycle_detector import detect_cycles
        from cycle_analyzer.combination_analyzer import analyze_combinations, compute_single_cycle_hit_rates
        from cycle_analyzer.report_generator import generate_report
    except ImportError as e:
        console.print(f"[red]Erreur d'import : {e}[/red]")
        console.print("[yellow]Installez les dépendances : pip install -r requirements.txt[/yellow]")
        sys.exit(1)

    from cycle_analyzer.data_fetcher import _resolve_ticker
    ticker = _resolve_ticker(args.ticker.upper())
    if ticker != args.ticker.upper():
        console.print(f"[dim]Ticker résolu : [bold]{args.ticker}[/bold] → [bold cyan]{ticker}[/bold cyan][/dim]")

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
            _src = f"depuis {args.start}" if args.start else f"période {args.period}"
            t1 = progress.add_task(f"Téléchargement des données pour {ticker} ({_src})…", total=None)
            try:
                data = fetch_data(ticker, period=args.period, interval=args.interval,
                                  start=args.start)
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

        if args.SL is not None:
            _run_sl_simulation(console, prices, dates, combo, args.SL, ticker,
                               f"selection_{'_'.join(str(p) for p in sel_periods)}_SL{args.SL}.png",
                               args.no_browser, fixed=_sl_fixed_mode)
        else:
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

        import warnings as _warn
        import matplotlib.pyplot as _plt
        from cycle_analyzer.cycle_detector import (
            CycleInfo as _CycleInfo, _phase_state as _phase_st,
        )
        from cycle_analyzer.combination_analyzer import get_custom_combination as _gcc
        from cycle_analyzer.visualizer import plot_combination as _plot_combo, plot_single_cycle as _plot_single

        N = len(prices)
        detrended_g, trend_g = _detrend_log(prices)

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
        ptable.add_column("Sine TV [dernier bar]", justify="right", style="bold magenta")
        tv_sines = []
        for sp, A_s, B_s, amp_s, psi, ago in coeff_table:
            tv_sine = _math.sin(2 * _math.pi * ago / sp)
            tv_sines.append((sp, ago, tv_sine))
            ptable.add_row(str(sp), f"{A_s:.4f}", f"{B_s:.4f}", f"{_math.degrees(psi):.1f}°", str(ago), f"{tv_sine:+.4f}")
        console.print(ptable)

        anchor_times = [
            int(dates[max(0, N - 1 - ago)].timestamp() * 1000)
            for ago in ago_values
        ]
        script = generate_pinescript(ticker, pine_periods, ago_values, anchor_times)

        # Inject a verification header so the user can check the correct script is loaded
        _last_date = dates[-1].strftime("%Y-%m-%d")
        _sines_str = "  |  ".join(f"Cycle {p}b ≈ {sv:+.4f}" for p, _, sv in tv_sines)
        _hdr = (
            f"// Généré le {_last_date}  ·  Ticker: {ticker}  ·  Périodes: {', '.join(str(p) for p in pine_periods)}\n"
            f"// Ago calculés : {', '.join(str(a) for a in ago_values)}\n"
            f"// Sine attendu [dernier bar] : {_sines_str}\n"
            f"// → Si TradingView affiche d'autres valeurs, recharger ce script\n"
        )
        _pine_lines = script.split('\n')
        script = _pine_lines[0] + '\n' + _hdr + '\n'.join(_pine_lines[1:])

        out_pine = Path(f"cycles_{ticker}_{'_'.join(str(p) for p in pine_periods)}.pine")
        out_pine.write_text(script, encoding="utf-8")

        # ── Generate comparison chart using IDENTICAL periods/phases as the Pine Script ──
        synth_cycles = []
        t_arr = np.arange(N, dtype=float)
        for sp, A_s, B_s, amp_s, psi, ago in coeff_table:
            state_s, osc_s, dir_s = _phase_st(A_s, B_s, float(sp), N - 1)
            osc_arr = np.exp(trend_g) * (
                1 + A_s * np.cos(2 * np.pi * t_arr / sp)
                + B_s * np.sin(2 * np.pi * t_arr / sp)
            )
            synth_cycles.append(_CycleInfo(
                period=sp, period_exact=float(sp),
                amplitude=round(amp_s * prices[-1], 2), strength=1.0, stability=0.0,
                phase_state=state_s, current_value=osc_s, current_direction=dir_s,
                oscillator=osc_arr, r_squared=0.0, amplitude_log=amp_s,
                coeff_a=A_s, coeff_b=B_s,
            ))

        _pine_combo = _gcc(prices, synth_cycles)
        _verify_str = "  |  ".join(f"Cycle {p}b ≈ {sv:+.3f}" for p, _, sv in tv_sines)

        if args.SL is not None:
            console.print(Panel(
                f"[bold green]Script Pine sauvegardé :[/bold green] {out_pine.resolve()}\n\n"
                "[dim]→ Pine Editor TradingView : ouvrir ce fichier, Ctrl+A, Ctrl+C, coller dans un Nouveau script.[/dim]\n"
                f"[dim]→ Vérification : au [/dim][bold]dernier bar[/bold][dim], les oscillateurs doivent afficher :[/dim]\n"
                f"   [bold magenta]{_verify_str}[/bold magenta]",
                border_style="green", expand=False,
            ))
            _sl_out = Path(f"cycles_{ticker}_{'_'.join(str(p) for p in pine_periods)}_SL{args.SL}.png")
            _run_sl_simulation(console, prices, dates, _pine_combo, args.SL, ticker,
                               str(_sl_out), args.no_browser, fixed=_sl_fixed_mode)
        else:
            out_chart = Path(f"cycles_{ticker}_{'_'.join(str(p) for p in pine_periods)}.png")
            with _warn.catch_warnings():
                _warn.simplefilter("ignore")
                if len(synth_cycles) == 1:
                    fig = _plot_single(prices, dates, synth_cycles[0], ticker)
                else:
                    fig = _plot_combo(prices, dates, _pine_combo, ticker)
                fig.savefig(out_chart, dpi=130, bbox_inches="tight", facecolor="#0d1117")
            _plt.close(fig)

            console.print(Panel(
                f"[bold green]Script Pine sauvegardé :[/bold green] {out_pine.resolve()}\n"
                f"[bold green]Graphique comparatif  :[/bold green] {out_chart.resolve()}\n\n"
                "[dim]→ Pine Editor TradingView : ouvrir ce fichier, Ctrl+A, Ctrl+C, coller dans un Nouveau script.[/dim]\n"
                f"[dim]→ Vérification : au [/dim][bold]dernier bar[/bold][dim], les oscillateurs doivent afficher :[/dim]\n"
                f"   [bold magenta]{_verify_str}[/bold magenta]",
                border_style="green", expand=False,
            ))

            # Open Pine script and chart
            try:
                import subprocess as _sp, platform as _plat
                _sys = _plat.system()
                if _sys == "Windows":
                    _sp.Popen(["notepad.exe", str(out_pine)])
                    console.print("[dim]✓ Fichier ouvert dans le Bloc-notes[/dim]")
                    ps_cmd = f'Set-Clipboard -Value (Get-Content -Path "{out_pine.resolve()}" -Raw)'
                    _sp.run(["powershell", "-Command", ps_cmd], check=False)
                    console.print("[dim]✓ Copié dans le presse-papiers (Ctrl+V pour coller)[/dim]")
                    _sp.Popen(["explorer", str(out_chart.resolve())])
                elif _sys == "Darwin":
                    _sp.Popen(["open", str(out_pine)])
                    _sp.run(["pbcopy"], input=script.encode("utf-8"), check=False)
                    _sp.Popen(["open", str(out_chart)])
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
        for c in cycles:
            c.hit_rate, c.short_hit_rate = compute_single_cycle_hit_rates(prices, c.period)
        progress.update(t2, description=f"[green]✓[/green] {len(cycles)} cycles détectés")
        progress.stop_task(t2)

        t3 = progress.add_task("Analyse des combinaisons de cycles…", total=None)
        _recency = None
        if args.recent is not None:
            _recency = args.recent if args.recent and args.recent > 0 else max(30.0, len(prices) / 4.0)
        _min_hit = args.reussite if args.reussite is not None else None
        combinations = analyze_combinations(prices, cycles, top_n_per_size=3,
                                            recency_halflife=_recency, min_hit=_min_hit,
                                            min_zones=args.zone)
        n_found = sum(len(v) for v in combinations.values())
        progress.update(t3, description=f"[green]✓[/green] {n_found} meilleures combinaisons trouvées")
        progress.stop_task(t3)

        t4 = progress.add_task("Génération du rapport HTML…", total=None)
        _opts = []
        if _min_hit is not None:
            _opts.append(f"Réussite ≥ {_min_hit:.0f}% (--reussite)")
        if _recency is not None:
            _opts.append(f"Priorité au récent (--recent, demi-vie {_recency:.0f} barres)")
        if args.zone is not None:
            _opts.append(f"≥ {args.zone} zones (--zone)")
        html = generate_report(
            ticker=ticker,
            ticker_info=ticker_info,
            prices=prices,
            dates=dates,
            cycles=cycles,
            combinations=combinations,
            period=args.period,
            interval=args.interval,
            options_note=" · ".join(_opts),
        )
        progress.update(t4, description="[green]✓[/green] Rapport généré")
        progress.stop_task(t4)

    if args.output:
        report_path = Path(args.output)
    else:
        import re as _re
        _tag = f"start-{args.start}" if args.start else args.period
        # Nettoie les caractères interdits dans un nom de fichier (Windows : / \ : * ? " < > |)
        _safe = _re.sub(r'[\\/:*?"<>|]+', "-", f"rapport_{ticker}_{_tag}")
        report_path = Path(f"{_safe}.html")

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
