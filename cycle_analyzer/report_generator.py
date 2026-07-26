from __future__ import annotations

from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from .cycle_detector import CycleInfo
from .combination_analyzer import (
    CombinationResult,
    get_custom_combination,
    combo_quality,
    _combos_too_similar,
)
from .visualizer import (
    fig_to_base64,
    plot_single_cycle,
    plot_combination,
)

_PHASE_BADGE = {
    "bullish": ("Haussier", "#238636", "#3fb950"),
    "bearish": ("Baissier", "#da3633", "#f85149"),
    "peak": ("Sommet", "#9e6a03", "#d29922"),
    "trough": ("Creux", "#9e6a03", "#d29922"),
}

_COMBO_PHASE = {
    "bullish": ("▲ Haussier", "#238636", "#3fb950"),
    "bearish": ("▼ Baissier", "#da3633", "#f85149"),
    "neutral": ("— Neutre",   "#21262d", "#8b949e"),
}


def _combo_phase(combo: CombinationResult) -> tuple:
    """Return (label, bg, fg) for the current phase of a combination."""
    if len(combo.bullish_mask) and combo.bullish_mask[-1]:
        return _COMBO_PHASE["bullish"]
    if len(combo.bearish_mask) and combo.bearish_mask[-1]:
        return _COMBO_PHASE["bearish"]
    return _COMBO_PHASE["neutral"]


def _cycle_row_html(c: CycleInfo) -> str:
    label, bg, fg = _PHASE_BADGE.get(c.phase_state, ("—", "#21262d", "#c9d1d9"))
    stab_weight = "bold" if c.stability >= 0.5 else "normal"
    stab_color = "#3fb950" if c.stability >= 0.5 else "#c9d1d9"
    return f"""
    <tr>
      <td>{c.rank}</td>
      <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{c.period}</span></td>
      <td>{c.amplitude:,.2f}</td>
      <td>{c.strength:.2f}</td>
      <td style="font-weight:{stab_weight};color:{stab_color}">{c.stability:.2f}</td>
      <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{label}</span></td>
    </tr>"""


def _summary_html(
    top_combos: List[CombinationResult],
    top_singles: List[tuple],          # List of (CycleInfo, CombinationResult)
) -> str:
    combo_rows = ""
    for i, c in enumerate(top_combos[:3], 1):
        bull_s = f"{c.total_return_pct:+.1f}%"
        bull_c = f"{c.compound_return_pct:+.1f}%"
        short_s = f"{-c.bearish_total_return_pct:+.1f}%"
        short_c = f"{c.short_compound_return_pct:+.1f}%"
        bull_col = "color:var(--green)" if c.compound_return_pct >= 0 else "color:var(--red)"
        short_col2 = "color:var(--green)" if c.short_compound_return_pct >= 0 else "color:var(--red)"
        ph_label, ph_bg, ph_fg = _combo_phase(c)
        combo_rows += f"""
        <tr>
          <td><span class="rank-badge">#{i}</span></td>
          <td style="font-weight:600;color:#fff">{c.label}</td>
          <td><span class="badge" style="background:{ph_bg}22;border:1px solid {ph_fg};color:{ph_fg}">{ph_label}</span></td>
          <td><span class="ret-val" data-simple="{bull_s}" data-compound="{bull_c}" style="{bull_col}">{bull_s}</span></td>
          <td><span class="ret-val" data-simple="{short_s}" data-compound="{short_c}" style="{short_col2}">{short_s}</span></td>
          <td style="color:var(--text2)">{c.hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{c.bearish_hit_rate:.0f}%</td>
        </tr>"""

    single_rows = ""
    for ci, sc in top_singles[:3]:
        label, bg, fg = _PHASE_BADGE.get(ci.phase_state, ("—", "#21262d", "#c9d1d9"))
        bull_s = f"{sc.total_return_pct:+.1f}%"
        bull_c = f"{sc.compound_return_pct:+.1f}%"
        short_s = f"{-sc.bearish_total_return_pct:+.1f}%"
        short_c = f"{sc.short_compound_return_pct:+.1f}%"
        bull_col = "color:var(--green)" if sc.compound_return_pct >= 0 else "color:var(--red)"
        short_col2 = "color:var(--green)" if sc.short_compound_return_pct >= 0 else "color:var(--red)"
        single_rows += f"""
        <tr>
          <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{ci.period}b</span></td>
          <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{label}</span></td>
          <td><span class="ret-val" data-simple="{bull_s}" data-compound="{bull_c}" style="{bull_col}">{bull_s}</span></td>
          <td><span class="ret-val" data-simple="{short_s}" data-compound="{short_c}" style="{short_col2}">{short_s}</span></td>
          <td style="color:var(--text2)">{sc.hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{sc.bearish_hit_rate:.0f}%</td>
        </tr>"""

    return f"""
<h2 style="margin-top:4px">Résumé — Meilleurs signaux</h2>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
  <div class="card" style="padding:14px">
    <div style="font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em;
                color:var(--text2);margin-bottom:10px">Top 3 meilleures combinaisons</div>
    <table>
      <thead><tr>
        <th>#</th><th>Combinaison</th><th>Phase actuelle</th>
        <th>Long ↑</th><th>Short ↓</th>
        <th>% réus. L</th><th>% réus. S</th>
      </tr></thead>
      <tbody>{combo_rows}</tbody>
    </table>
  </div>
  <div class="card" style="padding:14px">
    <div style="font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em;
                color:var(--text2);margin-bottom:10px">Top 3 Cycles simples</div>
    <table>
      <thead><tr>
        <th>Cycle</th><th>Phase</th>
        <th>Long ↑</th><th>Short ↓</th>
        <th>% réus. L</th><th>% réus. S</th>
      </tr></thead>
      <tbody>{single_rows}</tbody>
    </table>
  </div>
</div>"""


def _recap_table_html(combos: List[CombinationResult],
                      title: str = "Récapitulatif des combinaisons") -> str:
    """Tableau récapitulatif compact de toutes les combinaisons affichées :
    cycles utilisés, rendement long & short, % de réussite long & short."""
    if not combos:
        return ""
    # Déduplication des QUASI-DOUBLONS (cycles à ~18% près, ex: 201+136 / 199+136).
    # Une combinaison n'est masquée que si un quasi-jumeau déjà gardé la DOMINE à la
    # fois sur le long (rendement, réussite, zones) ET sur le short — sinon elle
    # apporte quelque chose (championne dans au moins une direction) et est gardée.
    uniq: List[CombinationResult] = []
    for c in sorted(combos, key=lambda r: combo_quality(r), reverse=True):
        sims = [k for k in uniq if _combos_too_similar(c.periods, k.periods)]
        if sims:
            dom_long = (
                any(k.total_return_pct >= c.total_return_pct for k in sims)
                and any(k.hit_rate >= c.hit_rate for k in sims)
                and any(k.n_zones >= c.n_zones for k in sims)
            )
            c_sret = -c.bearish_total_return_pct
            dom_short = (
                any(-k.bearish_total_return_pct >= c_sret for k in sims)
                and any(k.bearish_hit_rate >= c.bearish_hit_rate for k in sims)
                and any(len(k.bearish_zones) >= len(c.bearish_zones) for k in sims)
            )
            if dom_long and dom_short:
                continue
        uniq.append(c)
    rows = ""
    for c in uniq:
        long_ret = c.total_return_pct
        short_ret = -c.bearish_total_return_pct        # gain d'un short = -variation
        long_col = "var(--green)" if long_ret >= 0 else "var(--red)"
        short_col = "var(--green)" if short_ret >= 0 else "var(--red)"
        n_long = c.n_zones
        n_short = len(c.bearish_zones)
        avg_long = c.avg_return_pct                     # rendement moyen d'une zone haussière
        avg_short = (sum(-z.return_pct for z in c.bearish_zones) / n_short) if n_short else 0.0
        avg_long_col = "var(--green)" if avg_long >= 0 else "var(--red)"
        avg_short_col = "var(--green)" if avg_short >= 0 else "var(--red)"
        rows += f"""
        <tr>
          <td style="font-weight:600;color:#fff">{c.label}</td>
          <td style="color:{long_col}">{long_ret:+.1f}%</td>
          <td style="color:{short_col}">{short_ret:+.1f}%</td>
          <td style="color:var(--text2)">{c.hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{c.bearish_hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{n_long} / {n_short}</td>
          <td style="color:{avg_long_col}">{avg_long:+.1f}%</td>
          <td style="color:{avg_short_col}">{avg_short:+.1f}%</td>
        </tr>"""
    return f"""
<h2>{title}</h2>
<div class="card">
  <table>
    <thead><tr>
      <th>Cycles utilisés</th><th>Long ↑</th><th>Short ↓</th>
      <th>% réussite long</th><th>% réussite short</th>
      <th>Zones (L / S)</th><th>Rdt moy/zone L</th><th>Rdt moy/zone S</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _combo_card_short_html(combo: CombinationResult, img_b64: str, rank: int) -> str:
    """Card variant that highlights short performance (used in short-optimised section)."""
    short_zones_html = "".join(
        '<span class="zone-chip {cls}">{ret:+.1f}%</span>'.format(
            cls="pos" if z.return_pct <= 0 else "neg", ret=-z.return_pct
        )
        for z in combo.bearish_zones[:12]
    )
    short_more = f" +{len(combo.bearish_zones)-12} zones" if len(combo.bearish_zones) > 12 else ""

    zones_html = "".join(
        '<span class="zone-chip {cls}">{ret:+.1f}%</span>'.format(
            cls="pos" if z.return_pct >= 0 else "neg", ret=z.return_pct
        )
        for z in combo.zones[:8]
    )
    more = f" +{len(combo.zones)-8} zones" if len(combo.zones) > 8 else ""

    short_total = -combo.bearish_total_return_pct
    short_s = f"{short_total:+.1f}% ↓ short"
    short_c = f"{combo.short_compound_return_pct:+.1f}% ↓ short"
    bull_s = f"{combo.total_return_pct:+.1f}% ↑ long"
    bull_c = f"{combo.compound_return_pct:+.1f}% ↑ long"
    short_col = "green" if combo.short_compound_return_pct >= 0 else "red"
    bull_col = "green" if combo.compound_return_pct >= 0 else "red"

    ph_label, ph_bg, ph_fg = _combo_phase(combo)

    return f"""
    <div class="card" style="border-left:3px solid #f85149">
      <div class="card-header">
        <span class="rank-badge">#{rank}</span>
        <span class="combo-title">Cycles : {combo.label}</span>
        <span class="badge" style="background:{ph_bg}33;border:1px solid {ph_fg};color:{ph_fg};font-size:12px;padding:3px 10px">{ph_label}</span>
        <span class="stat-chip {short_col} ret-val" data-simple="{short_s}" data-compound="{short_c}" style="font-size:13px;font-weight:700">{short_s}</span>
        <span class="stat-chip red">{combo.bearish_hit_rate:.0f}% réussite short</span>
        <span class="stat-chip">{len(combo.bearish_zones)} zones baissières</span>
        <span class="stat-chip {bull_col} ret-val" data-simple="{bull_s}" data-compound="{bull_c}" style="opacity:.7">{bull_s}</span>
        <span class="stat-chip" style="opacity:.7">{combo.hit_rate:.0f}% réussite long</span>
      </div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:6px">
        Zones short (baissières) : {short_zones_html}{short_more}
      </div>
      <div style="font-size:11px;color:var(--text2);margin-bottom:10px;opacity:.6">
        Zones long (haussières) : {zones_html}{more}
      </div>
      <img src="data:image/png;base64,{img_b64}" class="chart-img" loading="lazy">
    </div>"""


def _combo_card_html(combo: CombinationResult, img_b64: str, rank: int) -> str:
    zones_html = "".join(
        '<span class="zone-chip {cls}">{ret:+.1f}%</span>'.format(
            cls="pos" if z.return_pct >= 0 else "neg", ret=z.return_pct
        )
        for z in combo.zones[:12]
    )
    more = f" +{len(combo.zones)-12} zones" if len(combo.zones) > 12 else ""

    # Short zones: gain = -price_change (positive when market fell)
    short_zones_html = "".join(
        '<span class="zone-chip {cls}">{ret:+.1f}%</span>'.format(
            cls="pos" if z.return_pct <= 0 else "neg", ret=-z.return_pct
        )
        for z in combo.bearish_zones[:12]
    )
    short_more = f" +{len(combo.bearish_zones)-12} zones" if len(combo.bearish_zones) > 12 else ""

    bull_s = f"{combo.total_return_pct:+.1f}% ↑ total"
    bull_c = f"{combo.compound_return_pct:+.1f}% ↑ total"
    short_total = -combo.bearish_total_return_pct
    short_s = f"{short_total:+.1f}% ↓ short"
    short_c = f"{combo.short_compound_return_pct:+.1f}% ↓ short"
    short_col = "green" if short_total >= 0 else "red"

    ph_label, ph_bg, ph_fg = _combo_phase(combo)

    short_section = ""
    if combo.bearish_zones:
        short_section = f"""
      <div style="margin-top:6px;font-size:11px;color:var(--text2);">
        Short (zones rouges) : {short_zones_html}{short_more}
      </div>"""

    return f"""
    <div class="card">
      <div class="card-header">
        <span class="rank-badge">#{rank}</span>
        <span class="combo-title">Cycles : {combo.label}</span>
        <span class="badge" style="background:{ph_bg}33;border:1px solid {ph_fg};color:{ph_fg};font-size:12px;padding:3px 10px">{ph_label}</span>
        <span class="stat-chip green ret-val" data-simple="{bull_s}" data-compound="{bull_c}">{bull_s}</span>
        <span class="stat-chip">{combo.hit_rate:.0f}% réussite long</span>
        <span class="stat-chip">{combo.n_zones} zones</span>
        <span class="stat-chip">{combo.avg_return_pct:+.2f}% moy/zone</span>
        <span class="stat-chip {short_col} ret-val" data-simple="{short_s}" data-compound="{short_c}">{short_s}</span>
        <span class="stat-chip">{combo.bearish_hit_rate:.0f}% réussite short</span>
      </div>
      <div class="zones-row">{zones_html}{more}</div>{short_section}
      <img src="data:image/png;base64,{img_b64}" class="chart-img" loading="lazy">
    </div>"""


def generate_report(
    ticker: str,
    ticker_info: dict,
    prices: np.ndarray,
    dates: pd.DatetimeIndex,
    cycles: List[CycleInfo],
    combinations: dict,          # {2: [CombinationResult...], 3: [CombinationResult...]}
    period: str,
    interval: str,
    options_note: str = "",
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_bars = len(prices)
    price_last = prices[-1]
    price_first = prices[0]
    total_perf = (price_last - price_first) / price_first * 100

    # Sections avec GRAPHIQUES : plafonnées à _CHART_CAP par catégorie. Le récap
    # (tableaux plus bas, sans image) montre TOUTES les combinaisons, lui.
    _CHART_CAP = 8
    sec2 = combinations.get(2, [])[:_CHART_CAP]
    sec3 = combinations.get(3, [])[:_CHART_CAP]
    secCourt = combinations.get("court", [])[:_CHART_CAP]

    short_combos = combinations.get("short_2", []) + combinations.get("short_3", [])
    # 3 meilleures combinaisons SHORT (par rendement short), dédupliquées
    short_top, _seen_s = [], set()
    for r in sorted(short_combos, key=lambda r: r.short_compound_return_pct, reverse=True):
        k = tuple(sorted(r.periods))
        if k in _seen_s:
            continue
        _seen_s.add(k)
        short_top.append(r)
        if len(short_top) >= 3:
            break

    # Un seul graphique par combinaison réellement affichée (sections uniquement)
    seen_ids: set = set()
    all_unique_combos: List[CombinationResult] = []
    for c in sec2 + sec3 + secCourt + short_top:
        if id(c) not in seen_ids:
            all_unique_combos.append(c)
            seen_ids.add(id(c))

    # ── Build chart images ────────────────────────────────────────────────────
    # Cycles simples : on n'affiche (stats + graphiques) QUE ceux dont la réussite
    # est >= 80%. Les autres ne sont pas montrés en détail.
    top3 = [c for c in cycles if c.hit_rate >= 80.0][:3]
    # Compute single-cycle stats (bullish/bearish totals) for each shown cycle
    top3_combos = [get_custom_combination(prices, [c]) for c in top3]
    imgs_top3 = [fig_to_base64(plot_single_cycle(prices, dates, c, ticker)) for c in top3]

    # ── Summary data: jusqu'à 5 combos variées (cycles simples non répétés) ──
    summary_combos = combinations.get("diverse", [])
    sorted_singles = sorted(zip(top3, top3_combos), key=lambda x: x[1].compound_return_pct, reverse=True)
    summary = _summary_html(summary_combos, list(sorted_singles)[:3])

    imgs_combos = {id(combo): fig_to_base64(plot_combination(prices, dates, combo, ticker))
                   for combo in all_unique_combos}

    # ── HTML ──────────────────────────────────────────────────────────────────
    top3_html = ""
    for c, sc, img in zip(top3, top3_combos, imgs_top3):
        label, bg, fg = _PHASE_BADGE.get(c.phase_state, ("—", "#21262d", "#c9d1d9"))
        short_total = -sc.bearish_total_return_pct
        short_col = "green" if short_total >= 0 else "red"
        bull_s = f"↑ {sc.total_return_pct:+.1f}% haussier"
        bull_c = f"↑ {sc.compound_return_pct:+.1f}% haussier"
        bear_s = f"↓ {short_total:+.1f}% short"
        bear_c = f"↓ {sc.short_compound_return_pct:+.1f}% short"
        n_long = sc.n_zones
        n_short = len(sc.bearish_zones)
        avg_long = sc.avg_return_pct
        avg_short = (sum(-z.return_pct for z in sc.bearish_zones) / n_short) if n_short else 0.0
        top3_html += f"""
        <div class="card">
          <div class="card-header">
            <span class="rank-badge">#{c.rank}</span>
            <span class="combo-title">Cycle {c.period} barres</span>
            <span class="badge" style="background:{bg}33;border:1px solid {fg};color:{fg}">{label}</span>
            <span class="stat-chip">Amp: {c.amplitude:,.2f}</span>
            <span class="stat-chip">Force: {c.strength:.2f}</span>
            <span class="stat-chip green">Stab: {c.stability:.2f}</span>
            <span class="stat-chip green ret-val" data-simple="{bull_s}" data-compound="{bull_c}">{bull_s}</span>
            <span class="stat-chip {short_col} ret-val" data-simple="{bear_s}" data-compound="{bear_c}">{bear_s}</span>
            <span class="stat-chip">{sc.hit_rate:.0f}% réussite long</span>
            <span class="stat-chip">{sc.bearish_hit_rate:.0f}% réussite short</span>
            <span class="stat-chip">Zones : {n_long} L / {n_short} S</span>
            <span class="stat-chip green">Rdt/zone : {avg_long:+.1f}% L / {avg_short:+.1f}% S</span>
          </div>
          <img src="data:image/png;base64,{img}" class="chart-img" loading="lazy">
        </div>"""

    # Section cycles simples : uniquement si au moins un cycle a >= 80% de réussite
    singles_html = (f'<h2>Cycles simples (réussite ≥ 80%)</h2>{top3_html}'
                    if top3_html.strip() else "")

    def _section_html(combo_list: List[CombinationResult], title: str, short_mode: bool = False) -> str:
        html_out = f'<h2>{title}</h2>'
        for rank, combo in enumerate(combo_list, 1):
            img = imgs_combos.get(id(combo), "")
            html_out += (_combo_card_short_html if short_mode else _combo_card_html)(combo, img, rank)
        return html_out

    # En mode filtre (--rendement / --reussite / --zone), on affiche TOUTES les
    # combinaisons qui passent, pas seulement un top 3 → les titres s'adaptent.
    _filtered = any(tag in options_note for tag in ("--rendement", "--reussite", "--zone"))
    _p2 = "Combinaisons de 2 cycles (toutes celles qui passent le filtre)" if _filtered else "Top 3 — Combinaisons de 2 cycles"
    _p3 = "Combinaisons de 3 cycles (toutes celles qui passent le filtre)" if _filtered else "Top 3 — Combinaisons de 3 cycles"
    _pc = "Combinaisons de cycles courts (&lt; 200 jours) — toutes celles qui passent" if _filtered else "Top 3 — Combinaisons de cycles courts (&lt; 200 jours)"

    combos_html = _section_html(sec2, _p2)
    combos_html += _section_html(sec3, _p3)
    if secCourt:
        combos_html += _section_html(secCourt, _pc)

    # Short section : les 3 MEILLEURES combinaisons pour le short (calculées plus haut)
    combos_html += _section_html(short_top, "Top 3 — Meilleures combinaisons pour le SHORT ↓", short_mode=True)

    # Tableau récapitulatif du HAUT : combinaisons long proposées, cycles UNIQUES
    # inclus (ceux qui passent le filtre) + paires + triples + courts.
    recap_html = _recap_table_html(
        combinations.get(1, []) + combinations.get(2, [])
        + combinations.get(3, []) + combinations.get("court", [])
    )

    # Tableau FINAL (bas de page) : TOUTES les combinaisons proposées, tous types
    # confondus — cycle unique, double, triple, cycles courts ET short.
    all_proposed = (
        combinations.get(1, []) + combinations.get(2, []) + combinations.get(3, [])
        + combinations.get("court", [])
        + combinations.get("short_1", [])
        + combinations.get("short_2", []) + combinations.get("short_3", [])
    )
    recap_full_html = _recap_table_html(all_proposed, title="Toutes les combinaisons proposées")

    table_rows = "\n".join(_cycle_row_html(c) for c in cycles)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analyse des Cycles — {ticker}</title>
<style>
  :root {{
    --bg: #0d1117; --panel: #161b22; --border: #21262d;
    --text: #c9d1d9; --text2: #8b949e; --green: #3fb950; --red: #f85149;
    --orange: #d29922; --blue: #58a6ff; --purple: #bc8cff;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, 'Segoe UI', sans-serif;
          font-size: 13px; line-height: 1.5; padding: 24px; }}
  h1 {{ font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 4px; }}
  h2 {{ font-size: 15px; font-weight: 600; color: var(--text); margin: 28px 0 12px;
        border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .meta {{ color: var(--text2); font-size: 12px; margin-bottom: 24px; }}
  .kpi-row {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }}
  .kpi {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
          padding: 12px 18px; min-width: 120px; }}
  .kpi-label {{ font-size: 11px; color: var(--text2); text-transform: uppercase; letter-spacing: .05em; }}
  .kpi-val {{ font-size: 20px; font-weight: 700; color: #fff; margin-top: 2px; }}
  .kpi-val.green {{ color: var(--green); }}
  .kpi-val.red {{ color: var(--red); }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  thead th {{ background: var(--panel); color: var(--text2); font-size: 11px;
               text-transform: uppercase; letter-spacing: .06em;
               padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }}
  tbody tr:hover {{ background: #1c2128; }}
  tbody td {{ padding: 7px 10px; border-bottom: 1px solid #1c2128; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px;
            font-size: 11.5px; font-weight: 600; }}
  .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
           padding: 16px; margin-bottom: 18px; }}
  .card-header {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }}
  .rank-badge {{ background: var(--border); border-radius: 4px; padding: 2px 7px;
                  font-size: 11px; font-weight: 700; color: var(--text2); }}
  .combo-title {{ font-weight: 700; font-size: 14px; color: #fff; }}
  .stat-chip {{ background: #21262d; border: 1px solid #30363d; border-radius: 6px;
                padding: 2px 8px; font-size: 11.5px; color: var(--text); }}
  .stat-chip.green {{ border-color: #238636; background: #23863620; color: var(--green); }}
  .stat-chip.red {{ border-color: #da3633; background: #da363320; color: var(--red); }}
  .zone-chip {{ display: inline-block; margin: 2px; padding: 1px 7px;
                border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .zone-chip.pos {{ background: #23863630; border: 1px solid #238636; color: var(--green); }}
  .zone-chip.neg {{ background: #da363330; border: 1px solid #da3633; color: var(--red); }}
  .zones-row {{ margin-bottom: 10px; line-height: 1.8; }}
  .chart-img {{ width: 100%; border-radius: 6px; display: block; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  @media (max-width: 800px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  .tab-bar {{ display: flex; gap: 6px; margin-bottom: 20px; }}
  .tab-btn {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
              padding: 6px 16px; font-size: 12px; color: var(--text2); cursor: pointer; }}
  .tab-btn:hover {{ border-color: var(--blue); color: var(--blue); }}
  .tab-btn.active {{ background: #1f3249; border-color: var(--blue); color: var(--blue);
                     font-weight: 600; }}
  .perf-banner {{ display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
                  background: var(--panel); border: 1px solid var(--border);
                  border-left: 4px solid {('#3fb950' if total_perf >= 0 else '#f85149')};
                  border-radius: 10px; padding: 16px 22px; margin-bottom: 20px; }}
  .perf-banner .main-ret {{ font-size: 36px; font-weight: 800;
                             color: {('#3fb950' if total_perf >= 0 else '#f85149')}; }}
  .perf-banner .perf-label {{ font-size: 11px; color: var(--text2); text-transform: uppercase;
                               letter-spacing: .06em; margin-bottom: 2px; }}
  .perf-banner .perf-detail {{ font-size: 13px; color: var(--text); }}
  .perf-banner .sep {{ width: 1px; height: 40px; background: var(--border); }}
</style>
</head>
<body>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('simple',this)">Somme des zones (simple)</button>
  <button class="tab-btn" onclick="switchTab('compound',this)">Rendement composé (réinvestissement)</button>
</div>
<script>
function switchTab(mode, btn) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.ret-val').forEach(el => {{
    el.textContent = el.dataset[mode];
  }});
}}
</script>

<h1>Analyse des Cycles — {ticker_info.get('name', ticker)} ({ticker.upper()})</h1>
<div class="meta">
  Généré le {now} &nbsp;|&nbsp;
  Données : du {dates[0].strftime('%d/%m/%Y')} au {dates[-1].strftime('%d/%m/%Y')} &nbsp;|&nbsp;
  Intervalle : {interval} &nbsp;|&nbsp; {n_bars} barres
</div>
{f'<div class="meta" style="margin-top:6px"><span class="badge" style="background:#1f6feb22;border:1px solid #1f6feb;color:#58a6ff;padding:3px 10px">Filtres actifs : {options_note}</span></div>' if options_note else ''}

<div class="perf-banner">
  <div>
    <div class="perf-label">Rendement Buy &amp; Hold</div>
    <div class="main-ret">{total_perf:+.1f}%</div>
  </div>
  <div class="sep"></div>
  <div>
    <div class="perf-label">Prix initial ({dates[0].strftime('%d/%m/%Y')})</div>
    <div class="perf-detail">{price_first:,.2f}</div>
  </div>
  <div class="sep"></div>
  <div>
    <div class="perf-label">Prix final ({dates[-1].strftime('%d/%m/%Y')})</div>
    <div class="perf-detail">{price_last:,.2f}</div>
  </div>
  <div class="sep"></div>
  <div>
    <div class="perf-label">Gain / Perte par part</div>
    <div class="perf-detail" style="color:{('#3fb950' if total_perf >= 0 else '#f85149')}">{price_last - price_first:+,.2f}</div>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi">
    <div class="kpi-label">Dernier prix</div>
    <div class="kpi-val">{price_last:,.2f}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Cycles détectés</div>
    <div class="kpi-val">{len(cycles)}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Meilleur cycle</div>
    <div class="kpi-val">{cycles[0].period if cycles else '—'} barres</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Stabilité max</div>
    <div class="kpi-val green">{cycles[0].stability if cycles else 0:.2f}</div>
  </div>
</div>

{summary}

{recap_html}

<h2>Tableau Complet des Cycles</h2>
<div class="card">
  <table>
    <thead>
      <tr>
        <th>#</th><th>Longueur (barres)</th><th>Amplitude</th>
        <th>Force</th><th>Stabilité</th><th>Phase actuelle</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>
</div>

{singles_html}

<p style="color:var(--text2);margin-bottom:14px;font-size:12px;">
  <span style="color:#3fb950">■</span> Zones vertes : tous les cycles simultanément haussiers (rendement affiché en haut).
  &nbsp;<span style="color:#f85149">■</span> Zones rouges : tous les cycles simultanément baissiers (rendement affiché en bas).
</p>
{combos_html}

{recap_full_html}

<hr style="border-color:var(--border);margin:32px 0 16px;">
<p style="color:var(--text2);font-size:11px;">
  Méthode : Décomposition par FFT sur log-prix désaisonnalisés + ajustement sinusoïdal par MCO.
  La stabilité est mesurée sur fenêtres glissantes. Ce document est à usage analytique uniquement.
</p>
</body>
</html>"""

    return html
