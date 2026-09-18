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


# Jours calendaires par barre (séance). Mis à jour au début de generate_report
# selon la fenêtre de données. Sert à AFFICHER toutes les durées en JOURS
# (l'interne reste en barres). ~1.44 en journalier (week-ends + fériés sautés).
_DPB: float = 1.0


def _d(bars) -> int:
    """Convertit un nombre de barres en JOURS calendaires (pour l'affichage)."""
    return int(round(float(bars) * _DPB))


def _combo_days_label(combo) -> str:
    """Libellé d'une combinaison en JOURS : '116 + 256 j' (au lieu de '80 + 177')."""
    return " + ".join(str(_d(c.period)) for c in combo.cycles) + " j"


def _cycle_period_label(c: CycleInfo) -> str:
    """Libellé COURT d'un cycle (badge), en JOURS : '2095 j' ou, si asymétrique,
    '2095 j ↑1524/↓571'."""
    a = getattr(c, "asym", None)
    return f"{_d(c.period)} j ↑{_d(a[0])}/↓{_d(a[1])}" if a else f"{_d(c.period)} j"


def _leg_split(c: CycleInfo):
    """(U, D) en barres d'un cycle = son découpage hausse / baisse. Un cycle
    symétrique (sans masque) est traité comme moitié-moitié."""
    a = getattr(c, "asym", None)
    if a:
        return float(a[0]), float(a[1])
    return c.period / 2.0, c.period / 2.0


def _is_cycle_whole(c: CycleInfo) -> bool:
    """Cycle « ENTIER » = autant de jours de hausse que de baisse (à ±10 % de la
    période près). Un cycle symétrique l'est par construction."""
    U, D = _leg_split(c)
    tot = U + D
    return tot > 0 and abs(U - D) <= 0.10 * tot


def _cycle_whole_kind(c: CycleInfo):
    """Classe un cycle : 'parfait' (hausse = baisse au barreau près, ou cycle
    symétrique), 'presque' (à ±10 % près sans être exact), ou None (déséquilibré)."""
    a = getattr(c, "asym", None)
    if not a:
        return "parfait"                       # symétrique = parfaitement entier
    U, D = float(a[0]), float(a[1])
    tot = U + D
    if tot <= 0:
        return None
    if round(U) == round(D):
        return "parfait"
    if abs(U - D) <= 0.10 * tot:
        return "presque"
    return None


def _combo_whole_kind(combo):
    """'parfait' si TOUS les cycles sont parfaitement entiers ; 'presque' si tous
    sont entiers mais au moins un seulement approximativement ; None sinon."""
    cycles = getattr(combo, "cycles", None)
    if not cycles:
        return None
    kinds = [_cycle_whole_kind(cy) for cy in cycles]
    if any(k is None for k in kinds):
        return None
    return "parfait" if all(k == "parfait" for k in kinds) else "presque"


def _combo_is_whole(combo) -> bool:
    """Une proposition est « entière » si TOUS les cycles qui la composent le sont."""
    return _combo_whole_kind(combo) is not None


def _cycle_title(c: CycleInfo) -> str:
    """Titre LONG d'un cycle simple (carte), en JOURS : asymétrique → détaille
    hausse/baisse."""
    a = getattr(c, "asym", None)
    if a:
        return f"Cycle {_d(c.period)} j · ↑{_d(a[0])} j hausse / ↓{_d(a[1])} j baisse"
    return f"Cycle {_d(c.period)} jours"


def _cycle_phase_badge(c: CycleInfo) -> tuple:
    """(label, bg, fg) de la phase actuelle d'un cycle. Les cycles asymétriques
    n'ont pas de `phase_state` → on la déduit de leur masque haussier explicite."""
    a = getattr(c, "asym", None)
    bm = getattr(c, "bull_mask", None)
    if a is not None and bm is not None and len(bm):
        return _PHASE_BADGE["bullish"] if bm[-1] else _PHASE_BADGE["bearish"]
    return _PHASE_BADGE.get(c.phase_state, ("—", "#21262d", "#c9d1d9"))


def _cycle_row_html(c: CycleInfo) -> str:
    label, bg, fg = _PHASE_BADGE.get(c.phase_state, ("—", "#21262d", "#c9d1d9"))
    stab_weight = "bold" if c.stability >= 0.5 else "normal"
    stab_color = "#3fb950" if c.stability >= 0.5 else "#c9d1d9"
    return f"""
    <tr>
      <td>{c.rank}</td>
      <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{_d(c.period)} j</span></td>
      <td>{c.amplitude:,.2f}</td>
      <td>{c.strength:.2f}</td>
      <td style="font-weight:{stab_weight};color:{stab_color}">{c.stability:.2f}</td>
      <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{label}</span></td>
    </tr>"""


def _combo_slug(periods) -> str:
    """Identifiant stable d'une combinaison = ses périodes triées, ex '47-119'.
    Sert à relier une case à cocher du récapitulatif à la carte-graphique
    correspondante plus bas dans le rapport."""
    try:
        return "-".join(str(int(round(float(p)))) for p in sorted(periods))
    except Exception:
        return ""


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
          <td style="font-weight:600;color:#fff">{_combo_days_label(c)}</td>
          <td><span class="badge" style="background:{ph_bg}22;border:1px solid {ph_fg};color:{ph_fg}">{ph_label}</span></td>
          <td><span class="ret-val" data-simple="{bull_s}" data-compound="{bull_c}" style="{bull_col}">{bull_s}</span></td>
          <td><span class="ret-val" data-simple="{short_s}" data-compound="{short_c}" style="{short_col2}">{short_s}</span></td>
          <td style="color:var(--text2)">{c.hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{c.bearish_hit_rate:.0f}%</td>
        </tr>"""

    single_rows = ""
    for ci, sc in top_singles[:3]:
        label, bg, fg = _cycle_phase_badge(ci)
        bull_s = f"{sc.total_return_pct:+.1f}%"
        bull_c = f"{sc.compound_return_pct:+.1f}%"
        short_s = f"{-sc.bearish_total_return_pct:+.1f}%"
        short_c = f"{sc.short_compound_return_pct:+.1f}%"
        bull_col = "color:var(--green)" if sc.compound_return_pct >= 0 else "color:var(--red)"
        short_col2 = "color:var(--green)" if sc.short_compound_return_pct >= 0 else "color:var(--red)"
        single_rows += f"""
        <tr>
          <td><span class="badge" style="background:{bg}22;border:1px solid {fg};color:{fg}">{_cycle_period_label(ci)}</span></td>
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


def _dedup_recap(combos: List[CombinationResult]) -> List[CombinationResult]:
    """Trie par qualité décroissante puis retire les QUASI-DOUBLONS (cycles à
    ~18% près). Une combinaison n'est masquée que si un quasi-jumeau déjà gardé
    la DOMINE à la fois sur le long ET sur le short — sinon elle apporte quelque
    chose (championne dans au moins une direction) et est gardée."""
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
    return uniq


def _prune_dominated_singles(cands: List[CombinationResult]) -> List[CombinationResult]:
    """Retire les cycles SIMPLES redondants. Deux cycles qui DÉMARRENT au même
    creux ET de période quasi identique, dont l'un est DOMINÉ par l'autre sur les
    QUATRE plans (rendement long, réussite long, rendement short, réussite short),
    sont le même cycle à une découpe près : on ne garde que le meilleur.

    On CONSERVE en revanche : les cycles à DÉPART différent (même proches), et les
    variantes qui gagnent au moins une dimension (ex. un peu moins rentable mais
    100 % de réussite). Les combinaisons ne sont jamais fusionnées.
    `cands` doit être trié par rendement décroissant (le meilleur est vu en 1er)."""
    def _start_key(c):
        if len(c.cycles) != 1:
            return ("combo", id(c))              # une combinaison n'est jamais fusionnée
        a = getattr(c.cycles[0], "asym", None)
        # même creux de départ (à ~30 barres près) ; les symétriques partagent la
        # même « origine » (toute la fenêtre) → même groupe.
        return ("anc", round(int(a[2]) / 30.0)) if a else ("sym",)

    def _dominates(k, c):
        return (k.total_return_pct >= c.total_return_pct
                and k.hit_rate >= c.hit_rate
                and -k.bearish_total_return_pct >= -c.bearish_total_return_pct
                and k.bearish_hit_rate >= c.bearish_hit_rate)

    kept: List[CombinationResult] = []
    for c in cands:
        sk = _start_key(c)
        redundant = any(
            _start_key(k) == sk
            and _combos_too_similar(c.periods, k.periods)
            and _dominates(k, c)
            for k in kept)
        if not redundant:
            kept.append(c)
    return kept



def _recap_table_html(combos: List[CombinationResult],
                      title: str = "Récapitulatif des combinaisons",
                      charted: dict = None, anchor_id: str = None,
                      presorted: bool = False) -> str:
    """Tableau récapitulatif compact de toutes les combinaisons affichées :
    cycles utilisés, rendement long & short, % de réussite long & short.
    `charted` : dict slug → id d'ancre de sa carte-graphique → la ligne devient
    un lien cliquable qui y saute. `anchor_id` : ancre HTML posée sur le titre
    (cible du bouton « retour au récapitulatif »)."""
    if not combos:
        return ""
    charted = charted or {}
    # presorted : la liste est déjà triée/sélectionnée (par rendement) en amont →
    # on l'affiche telle quelle, sans re-trier ni re-dédupliquer (sinon on
    # re-cacherait les variantes qu'on veut justement montrer).
    uniq = list(combos) if presorted else _dedup_recap(combos)
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
        _slug = _combo_slug(c.periods)
        _lab = _combo_days_label(c)
        _anchor = charted.get(_slug)
        _cell = (f'<a class="combo-link" href="#{_anchor}" data-combo="{_slug}" '
                 f'title="Aller au graphique">{_lab}</a>') if _anchor else _lab
        # Étoile = cycle ENTIER (autant de hausse que de baisse) → repérage rapide.
        #   ★ pleine blanche  = parfaitement symétrique (hausse = baisse)
        #   ☆ contour blanc   = presque symétrique (à ±10 % près)
        _star = ""
        _kind = _combo_whole_kind(c)
        if _kind is not None:
            _detail = " · ".join(
                (f"↑{_d(cy.asym[0])}/↓{_d(cy.asym[1])} j"
                 if getattr(cy, "asym", None) else f"{_d(cy.period)} j symétrique")
                for cy in c.cycles)
            _glyph = "★" if _kind == "parfait" else "☆"
            _tip = ("Cycle parfaitement entier — autant de hausse que de baisse"
                    if _kind == "parfait" else
                    "Cycle presque entier — hausse ≈ baisse (à ±10 %)")
            _star = (f' <span class="whole-star" style="color:#fff;font-size:9px;'
                     f'vertical-align:1px" title="{_tip} ({_detail})">{_glyph}</span>')
        rows += f"""
        <tr class="draggable-row" draggable="true">
          <td class="chk-cell"><input type="checkbox" class="mask-chk" data-combo="{_slug}" title="Masquer le graphique de cette combinaison plus bas"></td>
          <td style="font-weight:600;color:#fff"><span class="drag-grip" title="Glisser pour réordonner">⠿</span>{_cell}{_star}</td>
          <td style="color:{long_col}">{long_ret:+.1f}%</td>
          <td style="color:{short_col}">{short_ret:+.1f}%</td>
          <td style="color:var(--text2)">{c.hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{c.bearish_hit_rate:.0f}%</td>
          <td style="color:var(--text2)">{n_long} / {n_short}</td>
          <td style="color:{avg_long_col}">{avg_long:+.1f}%</td>
          <td style="color:{avg_short_col}">{avg_short:+.1f}%</td>
        </tr>"""
    _idattr = f' id="{anchor_id}"' if anchor_id else ""
    return f"""
<h2{_idattr}>{title}
  <span style="font-size:11px;font-weight:400;color:var(--text2)">
    &nbsp;— cliquez une combinaison pour aller à son graphique · glissez la poignée ⠿ pour réordonner · cochez la case pour masquer le graphique · <span style="color:#fff">★</span> = cycle parfaitement entier (hausse = baisse), <span style="color:#fff">☆</span> = presque entier (±10 %).
  </span></h2>""" + f"""
<div class="card">
  <table>
    <thead><tr>
      <th class="chk-cell"><input type="checkbox" class="mask-all" title="Tout cocher / décocher"></th><th>Cycles utilisés</th><th>Long ↑</th><th>Short ↓</th>
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
    <div class="card combo-card" id="cs-{_combo_slug(combo.periods)}" data-combo="{_combo_slug(combo.periods)}" style="border-left:3px solid #f85149">
      <div class="card-header">
        <span class="rank-badge">#{rank}</span>
        <span class="combo-title">Cycles : {_combo_days_label(combo)}</span>
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
    <div class="card combo-card" id="c-{_combo_slug(combo.periods)}" data-combo="{_combo_slug(combo.periods)}">
      <div class="card-header">
        <span class="rank-badge">#{rank}</span>
        <span class="combo-title">Cycles : {_combo_days_label(combo)}</span>
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

    # Toutes les durées sont AFFICHÉES en jours calendaires : on fixe le facteur
    # barres → jours d'après la fenêtre de données (l'interne reste en barres).
    global _DPB
    _hist_days = int((dates[-1] - dates[0]).days)
    _DPB = _hist_days / max(n_bars - 1, 1)

    sec2 = combinations.get(2, [])
    sec3 = combinations.get(3, [])
    secCourt = combinations.get("court", [])

    # RÉCAPITULATIF PLAFONNÉ : on ne garde que les RECAP_MAX meilleures propositions
    # (cycles simples + paires + triples + courts, triées par qualité, dédupliquées).
    # Les GRAPHIQUES ne sont tracés QUE pour ces lignes-là : les lignes du bas du
    # récap n'étaient jamais utilisées et généraient trop de graphiques.
    RECAP_MAX = 20

    def _sig(c):
        # signature EXACTE d'un cycle/combinaison : période + découpage (U/D) +
        # ancrage de chacun de ses cycles → deux variantes d'une même période
        # (départ/découpage différent) ont des signatures DIFFÉRENTES et sont
        # toutes deux gardées.
        return tuple(sorted(
            (cy.period,) + (tuple(cy.asym) if getattr(cy, "asym", None) else ())
            for cy in c.cycles))

    # RÉCAPITULATIF = les RECAP_MAX cycles au MEILLEUR RENDEMENT (long), cycles
    # simples ET combinaisons confondus. On garde TOUTES les variantes à bon
    # rendement — y compris plusieurs versions d'une même période qui « démarrent »
    # à un endroit différent — et on ne retire que les doublons EXACTS. Les
    # graphiques ne sont tracés que pour ces lignes.
    _seen_sig, _recap_top = set(), []
    _by_return = sorted(list(combinations.get(1, [])) + sec2 + sec3 + secCourt,
                        key=lambda r: r.total_return_pct, reverse=True)
    # Retire les quasi-doublons DOMINÉS d'un même départ (ex. 105 j et 106 j partant
    # du même creux, le 106 j étant battu sur tout) — mais garde les départs
    # différents et les variantes qui gagnent au moins une dimension.
    _by_return = _prune_dominated_singles(_by_return)
    for c in _by_return:
        s = _sig(c)
        if s in _seen_sig:
            continue
        _seen_sig.add(s)
        _recap_top.append(c)
        if len(_recap_top) >= RECAP_MAX:
            break

    # GARANTIE « chaque DÉPART distinct est représenté ». Un même cycle ancré à un
    # creux plus tardif (donc « démarré plus tard ») est un cycle DIFFÉRENT : s'il a
    # un bon rendement il doit figurer au récap même si le tri par rendement l'a
    # relégué après les RECAP_MAX premiers — souvent monopolisés par un seul départ
    # (plusieurs longueurs voisines ancrées au même creux). On ajoute donc, pour
    # chaque départ ABSENT du top, son meilleur cycle simple s'il est à bon rendement.
    def _anchor_key(c):
        if len(c.cycles) != 1:
            return None                       # une combinaison n'a pas de départ unique
        a = getattr(c.cycles[0], "asym", None)
        if not a:
            return None                       # cycle symétrique : pas d'ancrage réel
        return round(int(a[2]) / 30.0)        # regroupe les ancres d'un même creux
    _repr = {_anchor_key(c) for c in _recap_top}
    _repr.discard(None)
    _floor = 0.30 * (_recap_top[0].total_return_pct if _recap_top else 0.0)
    _champ: dict = {}                          # meilleur cycle simple par départ absent
    for c in _by_return:                       # déjà trié par rendement décroissant
        k = _anchor_key(c)
        if k is None or k in _repr or k in _champ:
            continue
        if c.total_return_pct >= _floor:       # « bon rendement » = >= 30 % du meilleur
            _champ[k] = c
    for c in _champ.values():
        s = _sig(c)
        if s not in _seen_sig:
            _seen_sig.add(s)
            _recap_top.append(c)
    # On garde l'affichage classé par RENDEMENT décroissant (champions inclus).
    _recap_top.sort(key=lambda r: r.total_return_pct, reverse=True)
    _recap_ids = {id(c) for c in _recap_top}
    sec2 = [c for c in sec2 if id(c) in _recap_ids]
    sec3 = [c for c in sec3 if id(c) in _recap_ids]
    secCourt = [c for c in secCourt if id(c) in _recap_ids]

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

    # ── Cycles simples affichés (stats + graphiques) ───────────────────────────
    # COHÉRENTS avec le récap :
    #  - mode filtre : exactement les cycles simples qui PASSENT le filtre
    #    (results[1]), classés par rendement — les mêmes que le tableau ;
    #  - sinon (défaut) : les cycles simples à réussite >= 80%.
    # Y a-t-il un filtre actif ? (pour le titre de la section cycles simples)
    _filtered = any(tag in options_note for tag in ("--rendement", "--reussite", "--zone", "--court"))
    # Cycles simples affichés = ceux de results[1] RETENUS dans le récap plafonné
    # → cartes et récap montrent EXACTEMENT les mêmes cycles simples.
    _single_combos = [c for c in combinations.get(1, []) if id(c) in _recap_ids]
    # On garde le cycle RÉELLEMENT utilisé par la combo (sc.cycles[0]) : c'est lui
    # qui porte l'éventuelle asymétrie (masque + ↑U/↓D). Ne PAS le remplacer par un
    # cycle symétrique de même période (sinon un cycle simple asym plus performant
    # serait « re-symétrisé » à l'affichage).
    top3 = [sc.cycles[0] for sc in _single_combos]
    top3_combos = list(_single_combos)
    imgs_top3 = [fig_to_base64(plot_single_cycle(prices, dates, c, ticker)) for c in top3]

    # ── Summary data: jusqu'à 5 combos variées (cycles simples non répétés) ──
    summary_combos = combinations.get("diverse", [])
    sorted_singles = sorted(zip(top3, top3_combos), key=lambda x: x[1].compound_return_pct, reverse=True)
    summary = _summary_html(summary_combos, list(sorted_singles)[:3])

    imgs_combos = {id(combo): fig_to_base64(plot_combination(prices, dates, combo, ticker))
                   for combo in all_unique_combos}

    # ── HTML ──────────────────────────────────────────────────────────────────
    top3_html = ""
    for _idx, (c, sc, img) in enumerate(zip(top3, top3_combos, imgs_top3), 1):
        label, bg, fg = _cycle_phase_badge(c)
        _asym = getattr(c, "asym", None)
        _rank = _idx   # numérotation = ordre d'affichage (par rendement décroissant)
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
        # Chips descriptifs : cycle ASYMÉTRIQUE → découpage hausse/baisse (Amp/Force/
        # Stab n'ont pas de sens pour un masque asym). Sinon → Amp/Force/Stab classiques.
        if _asym:
            _U, _D, _phi = _asym
            desc_chips = (
                f'<span class="stat-chip green">↑ {_d(_U)} j hausse</span>'
                f'<span class="stat-chip red">↓ {_d(_D)} j baisse</span>'
                f'<span class="stat-chip">Période {_d(c.period)} j</span>'
            )
        else:
            desc_chips = (
                f'<span class="stat-chip">Amp: {c.amplitude:,.2f}</span>'
                f'<span class="stat-chip">Force: {c.strength:.2f}</span>'
                f'<span class="stat-chip green">Stab: {c.stability:.2f}</span>'
            )
        top3_html += f"""
        <div class="card combo-card" id="c-{_combo_slug(sc.periods)}" data-combo="{_combo_slug(sc.periods)}">
          <div class="card-header">
            <span class="rank-badge">#{_rank}</span>
            <span class="combo-title">{_cycle_title(c)}</span>
            <span class="badge" style="background:{bg}33;border:1px solid {fg};color:{fg}">{label}</span>
            {desc_chips}
            <span class="stat-chip green ret-val" data-simple="{bull_s}" data-compound="{bull_c}">{bull_s}</span>
            <span class="stat-chip {short_col} ret-val" data-simple="{bear_s}" data-compound="{bear_c}">{bear_s}</span>
            <span class="stat-chip">{sc.hit_rate:.0f}% réussite long</span>
            <span class="stat-chip">{sc.bearish_hit_rate:.0f}% réussite short</span>
            <span class="stat-chip">Zones : {n_long} L / {n_short} S</span>
            <span class="stat-chip green">Rdt/zone : {avg_long:+.1f}% L / {avg_short:+.1f}% S</span>
          </div>
          <img src="data:image/png;base64,{img}" class="chart-img" loading="lazy">
        </div>"""

    # Section cycles simples : titre selon le mode (filtre vs réussite >= 80%)
    _singles_title = ("Cycles simples (qui passent le filtre)" if _filtered
                      else "Cycles simples (réussite ≥ 80%)")
    singles_html = (f'<h2>{_singles_title}</h2>{top3_html}'
                    if top3_html.strip() else "")

    def _section_html(combo_list: List[CombinationResult], title: str, short_mode: bool = False) -> str:
        html_out = f'<h2>{title}</h2>'
        for rank, combo in enumerate(combo_list, 1):
            img = imgs_combos.get(id(combo), "")
            html_out += (_combo_card_short_html if short_mode else _combo_card_html)(combo, img, rank)
        return html_out

    # En mode filtre (--rendement / --reussite / --zone / --court), on affiche TOUTES
    # les combinaisons qui passent, pas seulement un top 3 → les titres s'adaptent.
    _p2 = "Combinaisons de 2 cycles (toutes celles qui passent le filtre)" if _filtered else "Top 3 — Combinaisons de 2 cycles"
    _p3 = "Combinaisons de 3 cycles (toutes celles qui passent le filtre)" if _filtered else "Top 3 — Combinaisons de 3 cycles"
    _pc = "Combinaisons de cycles courts (&lt; 200 jours) — toutes celles qui passent" if _filtered else "Top 3 — Combinaisons de cycles courts (&lt; 200 jours)"

    combos_html = _section_html(sec2, _p2)
    combos_html += _section_html(sec3, _p3)
    if secCourt:
        combos_html += _section_html(secCourt, _pc)

    # Short section : les 3 MEILLEURES combinaisons pour le short (calculées plus haut)
    combos_html += _section_html(short_top, "Top 3 — Meilleures combinaisons pour le SHORT ↓", short_mode=True)

    # Chaque combinaison graphée → ancre de sa carte (id). On PRIVILÉGIE la carte
    # LONG/simple (id « c-… ») ; les combos uniquement short pointent vers « cs-… ».
    # Les lignes du récap deviennent des liens cliquables vers ces ancres.
    _chart_anchor: dict = {}
    for sc in top3_combos:
        _chart_anchor.setdefault(_combo_slug(sc.periods), "c-" + _combo_slug(sc.periods))
    for c in (sec2 + sec3 + secCourt):
        _chart_anchor.setdefault(_combo_slug(c.periods), "c-" + _combo_slug(c.periods))
    for c in short_top:
        _chart_anchor.setdefault(_combo_slug(c.periods), "cs-" + _combo_slug(c.periods))

    # Tableau récapitulatif du HAUT : les RECAP_MAX meilleures propositions (les
    # mêmes que les graphiques ci-dessous — une ligne = un graphique).
    recap_html = _recap_table_html(
        _recap_top, charted=_chart_anchor, anchor_id="recap", presorted=True,
    )

    # Le récap du haut (plafonné à RECAP_MAX) sert désormais de référence unique :
    # on n'ajoute plus le grand tableau « Toutes les combinaisons proposées » (ses
    # lignes du bas n'étaient jamais utilisées et alourdissaient la page).
    recap_full_html = ""

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
  /* Récapitulatif : la case coche la combinaison → masque SON graphique plus bas
     (la ligne du tableau, elle, reste toujours affichée). */
  .chk-cell {{ width: 26px; text-align: center; padding-left: 6px; padding-right: 4px; }}
  .mask-chk, .mask-all {{ cursor: pointer; accent-color: var(--blue); }}
  .combo-card.chart-off {{ display: none; }}
  /* Lignes du récap cliquables → saut vers le graphique. */
  .combo-link {{ color: #fff; text-decoration: none; cursor: pointer;
                 border-bottom: 1px dotted var(--blue); }}
  .combo-link:hover {{ color: var(--blue); }}
  .combo-card:target {{ outline: 2px solid var(--blue); outline-offset: 3px; }}
  /* Glisser-déposer des lignes du récap pour les réordonner. */
  .drag-grip {{ cursor: grab; color: var(--text2); margin-right: 8px;
               user-select: none; font-size: 12px; letter-spacing: -1px; }}
  .drag-grip:active {{ cursor: grabbing; }}
  tr.draggable-row.dragging {{ opacity: .4; background: #1f3249; }}
  /* Flèche flottante « retour au récapitulatif » (haut-gauche). */
  .back-to-recap {{ position: fixed; top: 14px; left: 14px; z-index: 1000; display: none;
                    width: 38px; height: 38px; border-radius: 50%;
                    background: var(--blue); color: #fff; align-items: center;
                    justify-content: center; font-size: 20px; font-weight: 700;
                    text-decoration: none; box-shadow: 0 2px 10px rgba(0,0,0,.45);
                    opacity: .9; }}
  .back-to-recap:hover {{ opacity: 1; transform: scale(1.06); }}
  .back-to-recap.show {{ display: flex; }}
</style>
</head>
<body>

<a href="#recap" class="back-to-recap" title="Retour au récapitulatif">↑</a>

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
// Récapitulatif : cocher une combinaison masque SON graphique plus bas (la
// ligne du tableau reste). La case en tête d'un tableau coche/décoche tout.
document.addEventListener('DOMContentLoaded', function () {{
  function applyMask(cb) {{
    var slug = cb.dataset.combo;
    if (!slug) return;
    // Synchronise toutes les cases de MÊME combinaison (elle peut figurer dans
    // plusieurs tableaux récapitulatifs).
    document.querySelectorAll('.mask-chk[data-combo="' + slug + '"]').forEach(function (o) {{
      o.checked = cb.checked;
    }});
    // Masque / réaffiche toutes les cartes-graphiques de cette combinaison.
    document.querySelectorAll('.combo-card[data-combo="' + slug + '"]').forEach(function (card) {{
      card.classList.toggle('chart-off', cb.checked);
    }});
  }}
  document.querySelectorAll('.mask-chk').forEach(function (cb) {{
    cb.addEventListener('change', function () {{ applyMask(cb); }});
  }});
  // Case « tout cocher / décocher » : agit sur toutes les lignes de SON tableau.
  document.querySelectorAll('.mask-all').forEach(function (master) {{
    master.addEventListener('change', function () {{
      var table = master.closest('table');
      if (!table) return;
      table.querySelectorAll('.mask-chk').forEach(function (cb) {{
        cb.checked = master.checked;
        applyMask(cb);
      }});
    }});
  }});

  // Clic sur une combinaison du récap → si son graphique était masqué, on le
  // ré-affiche (et on décoche sa case) avant d'y sauter.
  document.querySelectorAll('.combo-link').forEach(function (a) {{
    a.addEventListener('click', function () {{
      var slug = a.dataset.combo;
      document.querySelectorAll('.combo-card[data-combo="' + slug + '"]').forEach(function (card) {{
        card.classList.remove('chart-off');
      }});
      document.querySelectorAll('.mask-chk[data-combo="' + slug + '"]').forEach(function (cb) {{
        cb.checked = false;
      }});
    }});
  }});

  // Glisser-déposer : réordonner les lignes du récap pour comparer des cycles.
  function _rowAfter(tbody, y) {{
    var rows = [].slice.call(tbody.querySelectorAll('tr.draggable-row:not(.dragging)'));
    var closest = null, closestOffset = -Infinity;
    rows.forEach(function (r) {{
      var box = r.getBoundingClientRect();
      var offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closestOffset) {{ closestOffset = offset; closest = r; }}
    }});
    return closest;
  }}
  document.querySelectorAll('table').forEach(function (table) {{
    var tbody = table.querySelector('tbody');
    if (!tbody || !tbody.querySelector('tr.draggable-row')) return;
    var dragEl = null;
    tbody.querySelectorAll('tr.draggable-row').forEach(function (tr) {{
      tr.addEventListener('dragstart', function (e) {{
        // Ne pas déclencher le glissement depuis la case ou le lien.
        if (e.target.closest('input, a')) {{ e.preventDefault(); return; }}
        dragEl = tr; tr.classList.add('dragging');
        if (e.dataTransfer) {{ e.dataTransfer.effectAllowed = 'move';
          try {{ e.dataTransfer.setData('text/plain', ''); }} catch (_e) {{}} }}
      }});
      tr.addEventListener('dragend', function () {{
        if (dragEl) dragEl.classList.remove('dragging'); dragEl = null;
      }});
    }});
    tbody.addEventListener('dragover', function (e) {{
      if (!dragEl || !tbody.contains(dragEl)) return;
      e.preventDefault();
      var after = _rowAfter(tbody, e.clientY);
      if (after == null) tbody.appendChild(dragEl);
      else tbody.insertBefore(dragEl, after);
    }});
  }});

  // Flèche « retour au récapitulatif » : visible seulement après défilement.
  var _back = document.querySelector('.back-to-recap');
  if (_back) {{
    var _toggle = function () {{ _back.classList.toggle('show', window.scrollY > 500); }};
    window.addEventListener('scroll', _toggle);
    _toggle();
  }}
}});
</script>

<h1>Analyse des Cycles — {ticker_info.get('name', ticker)} ({ticker.upper()})</h1>
<div class="meta">
  Généré le {now} &nbsp;|&nbsp;
  Données : du {dates[0].strftime('%d/%m/%Y')} au {dates[-1].strftime('%d/%m/%Y')} &nbsp;|&nbsp;
  Intervalle : {interval} &nbsp;|&nbsp; {n_bars} séances (~{_hist_days} jours)
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
    <div class="kpi-val">{_d(cycles[0].period) if cycles else '—'} jours</div>
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
        <th>#</th><th>Longueur (jours)</th><th>Amplitude</th>
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
