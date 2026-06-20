from __future__ import annotations

import math
from typing import List


def _compute_ago(A: float, B: float, T: float, N: int) -> int:
    """Compute the TradingView 'ago' offset aligning A*cos+B*sin to sin(2π*(bar-anchor)/T)."""
    psi = math.atan2(A, B)
    ago = ((N - 1) + psi * T / (2 * math.pi)) % T
    return int(round(ago))


def _generate_single_cycle(ticker: str, period: int, ago: int) -> str:
    """Pine Script v6 for a single cycle."""
    return (
        '//@version=6\n'
        '// Généré automatiquement par Analyseur de Cycles de Marché\n'
        '// Actif : ' + ticker + ' | Cycle : ' + str(period) + ' barres\n'
        'indicator("Cycle ' + str(period) + 'b — ' + ticker + '", overlay=true, max_labels_count=500)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// PARAMÈTRES\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'len1 = input.int(' + str(period) + ', "Longueur du cycle", minval=2)\n'
        'ago1 = input.int(' + str(ago) + ',  "Phase (ago)", minval=0)\n'
        'col1 = input.color(color.new(#58a6ff, 0), "Couleur oscillateur")\n'
        '\n'
        'grpD = "Affichage"\n'
        'showGreenBg = input.bool(true, "Zone haussière (fond vert)",  group=grpD)\n'
        'showRedBg   = input.bool(true, "Zone baissière (fond rouge)", group=grpD)\n'
        'showLabels  = input.bool(true, "Labels rendement par zone",   group=grpD)\n'
        'showTable   = input.bool(true, "Tableau récapitulatif",       group=grpD)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// SINUS\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'anchor1 = last_bar_index - ago1\n'
        's1      = math.sin(2 * math.pi * (bar_index - anchor1) / len1)\n'
        '\n'
        'bull1 = ta.change(s1) > 0\n'
        'bear1 = not bull1\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// PROCHAIN EXTRÊME\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'f_nextExtreme(l, a) =>\n'
        '    anc = last_bar_index - a\n'
        '    p   = float(bar_index - anc) % float(l)\n'
        '    p  := p < 0.0 ? p + float(l) : p\n'
        '    q   = float(l) / 4.0\n'
        '    p < q        ? math.round(q - p)              :\n'
        '     p < 3.0 * q ? math.round(3.0 * q - p)       :\n'
        '                   math.round(float(l) + q - p)\n'
        '\n'
        'nextExt1 = f_nextExtreme(len1, ago1)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// FOND DE ZONES\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'bgcolor(showGreenBg and bull1 ? color.new(#238636, 85) : na, title="Zone haussière")\n'
        'bgcolor(showRedBg   and bear1 ? color.new(#da3633, 85) : na, title="Zone baissière")\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// SUIVI DES RENDEMENTS\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'var float cumGreen = 0.0\n'
        'var float cumRed   = 0.0\n'
        'var float zOpen    = na\n'
        'var bool  wasGreen = false\n'
        'var bool  wasRed   = false\n'
        '\n'
        'if bull1 and not bull1[1]\n'
        '    zOpen    := close\n'
        '    wasGreen := true\n'
        '    wasRed   := false\n'
        '\n'
        'if not bull1 and bull1[1] and wasGreen and not na(zOpen)\n'
        '    zonePct = (close - zOpen) / zOpen * 100\n'
        '    cumGreen += zonePct\n'
        '    if showLabels\n'
        '        label.new(bar_index, high * 1.001,\n'
        '                  str.tostring(math.round(zonePct, 1)) + "%",\n'
        '                  color=color.new(#238636, 20), textcolor=color.white,\n'
        '                  style=label.style_label_down, size=size.tiny)\n'
        '    wasGreen := false\n'
        '    zOpen    := na\n'
        '\n'
        'if bear1 and not bear1[1]\n'
        '    zOpen  := close\n'
        '    wasRed  := true\n'
        '    wasGreen := false\n'
        '\n'
        'if not bear1 and bear1[1] and wasRed and not na(zOpen)\n'
        '    zonePct = (close - zOpen) / zOpen * 100\n'
        '    cumRed += zonePct\n'
        '    if showLabels\n'
        '        label.new(bar_index, low * 0.999,\n'
        '                  str.tostring(math.round(zonePct, 1)) + "%",\n'
        '                  color=color.new(#da3633, 20), textcolor=color.white,\n'
        '                  style=label.style_label_up, size=size.tiny)\n'
        '    wasRed  := false\n'
        '    zOpen   := na\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// TABLEAU\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'var table t = table.new(position.top_right, 3, 4,\n'
        '             bgcolor=color.new(#161b22, 5),\n'
        '             border_width=1, border_color=color.new(#30363d, 0),\n'
        '             frame_width=1,  frame_color=color.new(#30363d, 0))\n'
        '\n'
        'if barstate.islast and showTable\n'
        '    table.cell(t, 0, 0, "Cycle",       text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '    table.cell(t, 1, 0, "Long. / Ago", text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 0, "Phase",       text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '    table.cell(t, 0, 1, str.tostring(len1) + " barres", text_color=col1, text_size=size.small)\n'
        '    table.cell(t, 1, 1, "ago=" + str.tostring(ago1), text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 1, bull1 ? "▲ Haussier" : "▼ Baissier",\n'
        '               text_color=bull1 ? color.new(#3fb950, 0) : color.new(#f85149, 0), text_size=size.small)\n'
        '    table.cell(t, 0, 2, "Zones ↑ cumulé", text_color=color.new(#3fb950, 0), text_size=size.small)\n'
        '    table.cell(t, 1, 2, str.tostring(math.round(cumGreen, 1)) + "%",\n'
        '               text_color=color.new(#3fb950, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 2, "", text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '    table.cell(t, 0, 3, "Zones ↓ cumulé", text_color=color.new(#f85149, 0), text_size=size.small)\n'
        '    table.cell(t, 1, 3, str.tostring(math.round(cumRed, 1)) + "%",\n'
        '               text_color=color.new(#f85149, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 3, "", text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        '// ALERTES\n'
        '// ─────────────────────────────────────────────────────────────────────\n'
        'alertcondition(bull1 and not bull1[1], "Cycle haussier — ' + ticker + '",\n'
        '               "Début de phase haussière sur ' + ticker + ' (cycle ' + str(period) + 'b)")\n'
        'alertcondition(bear1 and not bear1[1], "Cycle baissier — ' + ticker + '",\n'
        '               "Début de phase baissière sur ' + ticker + ' (cycle ' + str(period) + 'b)")\n'
        'alertcondition(nextExt1 <= 3, "J-3 retournement imminent — ' + ticker + '",\n'
        '               "ATTENTION J-3 : retournement de cycle imminent sur ' + ticker + ' (' + str(period) + 'b)")\n'
    )


def generate_pinescript(
    ticker: str,
    periods: List[int],
    ago_values: List[int],
) -> str:
    """
    Generate TradingView Pine Script v6 for 1, 2 or 3 sine-based market cycles.
    ago_values[i] = computed phase offset for periods[i] (from _compute_ago).
    """
    n = len(periods)
    if n < 1 or n > 3:
        raise ValueError("Only 1, 2 or 3 cycles are supported")

    if n == 1:
        return _generate_single_cycle(ticker, periods[0], ago_values[0])

    # Pre-compute string fragments to avoid quote conflicts inside f-strings
    labels = ["Long", "Moyen", "Court"] if n == 3 else ["Long", "Court"]
    periods_plus = " + ".join(str(p) for p in periods)
    periods_comma = ", ".join(str(p) for p in periods)
    indicator_title = "Cycles " + periods_plus + " — " + ticker

    # ── Optional 3rd cycle blocks ─────────────────────────────────────────────
    if n == 3:
        block_params3 = (
            '\ngrp3 = "Cycle 3 (Court)"\n'
            "len3 = input.int(" + str(periods[2]) + ', "Longueur", minval=2, group=grp3)\n'
            "ago3 = input.int(" + str(ago_values[2]) + ',  "Phase (ago)", minval=0, group=grp3)\n'
            'col3 = input.color(color.new(#d29922, 0), "Couleur", group=grp3)\n'
        )
        block_sine3 = (
            "\nanchor3 = last_bar_index - ago3\n"
            "s3      = math.sin(2 * math.pi * (bar_index - anchor3) / len3)\n"
        )
        block_bull3 = "bull3 = ta.change(s3) > 0\nbear3 = not bull3\n"
        all_cond_extra = " and bull3"
        all_bear_extra = " and bear3"
        block_nextExt3 = "nextExt3 = f_nextExtreme(len3, ago3)\n"
        j3_extra = " or nextExt3 <= 3"
        osc_comment3 = '// plot(s3, "Cycle ' + str(periods[2]) + 'b", color=col3, linewidth=2)\n'
        longmed_bg = (
            "bgcolor(bull1 and bull2 and not bull3 ?"
            " color.new(#d29922, 93) : na, title=\"Long+Moyen haussiers\")\n"
        )
        n_table_rows = 6  # header + 3 cycles + 2 totals
        block_cell3 = (
            '    table.cell(t, 0, 3, "' + labels[2] + ' (" + str.tostring(len3) + "b)",'
            " text_color=col3, text_size=size.small)\n"
            '    table.cell(t, 1, 3, "ago=" + str.tostring(ago3),'
            " text_color=color.new(#c9d1d9, 0), text_size=size.small)\n"
            "    table.cell(t, 2, 3, bull3 ? \"▲ Haussier\" : \"▼ Baissier\",\n"
            "               text_color=bull3 ?"
            " color.new(#3fb950, 0) : color.new(#f85149, 0), text_size=size.small)\n"
        )
        block_alert3 = (
            "alertcondition(bull1 and bull2 and not bull3,"
            ' "Long+Moyen haussiers — ' + ticker + '",'
            ' "Cycles Long+Moyen haussiers, Court baissier — ' + ticker + '")\n'
            "alertcondition(not bull1 and not bull2 and bull3,"
            ' "Long+Moyen baissiers — ' + ticker + '",'
            ' "Cycles Long+Moyen baissiers, Court haussier — ' + ticker + '")\n'
        )
    else:
        block_params3 = ""
        block_sine3 = ""
        block_bull3 = ""
        all_cond_extra = ""
        all_bear_extra = ""
        block_nextExt3 = ""
        j3_extra = ""
        osc_comment3 = ""
        longmed_bg = ""
        n_table_rows = 5  # header + 2 cycles + 2 totals
        block_cell3 = ""
        block_alert3 = ""

    gains_row = n_table_rows - 2
    loss_row = n_table_rows - 1

    script = (
        '//@version=6\n'
        '// Généré automatiquement par Analyseur de Cycles de Marché\n'
        '// Actif : ' + ticker + ' | Cycles : ' + periods_plus + '\n'
        'indicator("' + indicator_title + '", overlay=true, max_labels_count=500, max_lines_count=200)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// PARAMÈTRES\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'grp1 = "Cycle 1 (' + labels[0] + ')"\n'
        'len1 = input.int(' + str(periods[0]) + ', "Longueur", minval=2, group=grp1)\n'
        'ago1 = input.int(' + str(ago_values[0]) + ',  "Phase (ago)", minval=0, group=grp1)\n'
        'col1 = input.color(color.new(#58a6ff, 0), "Couleur", group=grp1)\n'
        '\n'
        'grp2 = "Cycle 2 (' + labels[1] + ')"\n'
        'len2 = input.int(' + str(periods[1]) + ', "Longueur", minval=2, group=grp2)\n'
        'ago2 = input.int(' + str(ago_values[1]) + ',  "Phase (ago)", minval=0, group=grp2)\n'
        'col2 = input.color(color.new(#3fb950, 0), "Couleur", group=grp2)\n'
        + block_params3 +
        '\n'
        'grpD = "Affichage"\n'
        'showGreenBg = input.bool(true,  "Zones haussières (fond vert)",  group=grpD)\n'
        'showRedBg   = input.bool(true,  "Zones baissières (fond rouge)", group=grpD)\n'
        'showLabels  = input.bool(true,  "Labels rendement par zone",     group=grpD)\n'
        'showTable   = input.bool(true,  "Tableau récapitulatif",         group=grpD)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// CALCUL DES SINUS\n'
        '// anchor = last_bar_index - ago  =>  sin(2π*ago/len) aligne la phase au dernier bar\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'anchor1 = last_bar_index - ago1\n'
        's1      = math.sin(2 * math.pi * (bar_index - anchor1) / len1)\n'
        '\n'
        'anchor2 = last_bar_index - ago2\n'
        's2      = math.sin(2 * math.pi * (bar_index - anchor2) / len2)\n'
        + block_sine3 +
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// DIRECTIONS  (haussier = sinus montant)\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'bull1 = ta.change(s1) > 0\n'
        'bear1 = not bull1\n'
        'bull2 = ta.change(s2) > 0\n'
        'bear2 = not bull2\n'
        + block_bull3 +
        '\n'
        'allBull = bull1 and bull2' + all_cond_extra + '\n'
        'allBear = bear1 and bear2' + all_bear_extra + '\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// PROCHAIN EXTRÊME  (barres restantes jusqu\'au prochain pic ou creux)\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'f_nextExtreme(l, a) =>\n'
        '    anc = last_bar_index - a\n'
        '    p   = float(bar_index - anc) % float(l)\n'
        '    p  := p < 0.0 ? p + float(l) : p\n'
        '    q   = float(l) / 4.0\n'
        '    p < q        ? math.round(q - p)              :\n'
        '     p < 3.0 * q ? math.round(3.0 * q - p)       :\n'
        '                   math.round(float(l) + q - p)\n'
        '\n'
        'nextExt1 = f_nextExtreme(len1, ago1)\n'
        'nextExt2 = f_nextExtreme(len2, ago2)\n'
        + block_nextExt3 +
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// OSCILLATEURS  (décommenter et passer en overlay=false pour les voir)\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// plot(s1, "Cycle ' + str(periods[0]) + 'b", color=col1, linewidth=2)\n'
        '// plot(s2, "Cycle ' + str(periods[1]) + 'b", color=col2, linewidth=2)\n'
        + osc_comment3 +
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// FOND DE ZONES\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'bgcolor(showGreenBg and allBull ? color.new(#238636, 85) : na, title="Zone haussière")\n'
        'bgcolor(showRedBg   and allBear ? color.new(#da3633, 85) : na, title="Zone baissière")\n'
        + longmed_bg +
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// SUIVI DES RENDEMENTS PAR ZONE\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'var float cumGreen = 0.0\n'
        'var float cumRed   = 0.0\n'
        'var float zOpen    = na\n'
        'var bool  wasGreen = false\n'
        'var bool  wasRed   = false\n'
        '\n'
        'newGreen = allBull and not allBull[1]\n'
        'endGreen = not allBull and allBull[1]\n'
        'newRed   = allBear and not allBear[1]\n'
        'endRed   = not allBear and allBear[1]\n'
        '\n'
        'if newGreen\n'
        '    zOpen    := close\n'
        '    wasGreen := true\n'
        '    wasRed   := false\n'
        '\n'
        'if endGreen and wasGreen and not na(zOpen)\n'
        '    zonePct = (close - zOpen) / zOpen * 100\n'
        '    cumGreen += zonePct\n'
        '    if showLabels\n'
        '        label.new(bar_index, high * 1.001,\n'
        '                  str.tostring(math.round(zonePct, 1)) + "%",\n'
        '                  color=color.new(#238636, 20), textcolor=color.white,\n'
        '                  style=label.style_label_down, size=size.tiny)\n'
        '    wasGreen := false\n'
        '    zOpen    := na\n'
        '\n'
        'if newRed\n'
        '    zOpen  := close\n'
        '    wasRed  := true\n'
        '    wasGreen := false\n'
        '\n'
        'if endRed and wasRed and not na(zOpen)\n'
        '    zonePct = (close - zOpen) / zOpen * 100\n'
        '    cumRed += zonePct\n'
        '    if showLabels\n'
        '        label.new(bar_index, low * 0.999,\n'
        '                  str.tostring(math.round(zonePct, 1)) + "%",\n'
        '                  color=color.new(#da3633, 20), textcolor=color.white,\n'
        '                  style=label.style_label_up, size=size.tiny)\n'
        '    wasRed  := false\n'
        '    zOpen   := na\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// TABLEAU RÉCAPITULATIF\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'var table t = table.new(position.top_right, 3, ' + str(n_table_rows) + ',\n'
        '             bgcolor=color.new(#161b22, 5),\n'
        '             border_width=1, border_color=color.new(#30363d, 0),\n'
        '             frame_width=1,  frame_color=color.new(#30363d, 0))\n'
        '\n'
        'if barstate.islast and showTable\n'
        '    // En-têtes\n'
        '    table.cell(t, 0, 0, "Cycle",       text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '    table.cell(t, 1, 0, "Long. / Ago", text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 0, "Phase",       text_color=color.new(#c9d1d9, 0), bgcolor=color.new(#1c2128, 0), text_size=size.small)\n'
        '\n'
        '    // Cycle 1 — ' + labels[0] + '\n'
        '    table.cell(t, 0, 1, "' + labels[0] + ' (" + str.tostring(len1) + "b)", text_color=col1, text_size=size.small)\n'
        '    table.cell(t, 1, 1, "ago=" + str.tostring(ago1), text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 1, bull1 ? "▲ Haussier" : "▼ Baissier",\n'
        '               text_color=bull1 ? color.new(#3fb950, 0) : color.new(#f85149, 0), text_size=size.small)\n'
        '\n'
        '    // Cycle 2 — ' + labels[1] + '\n'
        '    table.cell(t, 0, 2, "' + labels[1] + ' (" + str.tostring(len2) + "b)", text_color=col2, text_size=size.small)\n'
        '    table.cell(t, 1, 2, "ago=" + str.tostring(ago2), text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '    table.cell(t, 2, 2, bull2 ? "▲ Haussier" : "▼ Baissier",\n'
        '               text_color=bull2 ? color.new(#3fb950, 0) : color.new(#f85149, 0), text_size=size.small)\n'
        + block_cell3 +
        '\n'
        '    // Rendement cumulé zones haussières\n'
        '    table.cell(t, 0, ' + str(gains_row) + ', "Zones ↑ cumulé", text_color=color.new(#3fb950, 0), text_size=size.small)\n'
        '    table.cell(t, 1, ' + str(gains_row) + ', str.tostring(math.round(cumGreen, 1)) + "%",\n'
        '               text_color=color.new(#3fb950, 0), text_size=size.small)\n'
        '    table.cell(t, 2, ' + str(gains_row) + ', "", text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '\n'
        '    // Rendement cumulé zones baissières\n'
        '    table.cell(t, 0, ' + str(loss_row) + ', "Zones ↓ cumulé",  text_color=color.new(#f85149, 0), text_size=size.small)\n'
        '    table.cell(t, 1, ' + str(loss_row) + ', str.tostring(math.round(cumRed, 1)) + "%",\n'
        '               text_color=color.new(#f85149, 0), text_size=size.small)\n'
        '    table.cell(t, 2, ' + str(loss_row) + ', "", text_color=color.new(#c9d1d9, 0), text_size=size.small)\n'
        '\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        '// ALERTES\n'
        '// ─────────────────────────────────────────────────────────────────────────────\n'
        'alertcondition(allBull, "Tous cycles haussiers — ' + ticker + '",\n'
        '               "Alignement HAUSSIER complet sur ' + ticker + ' (cycles ' + periods_comma + ')")\n'
        'alertcondition(allBear, "Tous cycles baissiers — ' + ticker + '",\n'
        '               "Alignement BAISSIER complet sur ' + ticker + ' (cycles ' + periods_comma + ')")\n'
        + block_alert3 +
        '\n'
        '// J-3 : avertissement 3 barres avant retournement\n'
        'alertcondition(allBull and (nextExt1 <= 3 or nextExt2 <= 3' + j3_extra + '),\n'
        '               "J-3 pic imminent — ' + ticker + '",\n'
        '               "ATTENTION J-3 : pic de cycle proche, retournement baissier probable sur ' + ticker + '")\n'
        'alertcondition(allBear and (nextExt1 <= 3 or nextExt2 <= 3' + j3_extra + '),\n'
        '               "J-3 creux imminent — ' + ticker + '",\n'
        '               "ATTENTION J-3 : creux de cycle proche, retournement haussier probable sur ' + ticker + '")\n'
    )
    return script
