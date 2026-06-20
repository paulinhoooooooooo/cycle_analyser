from __future__ import annotations

import math
from typing import List, Optional


def _compute_ago(A: float, B: float, T: float, N: int) -> int:
    """Compute the TradingView 'ago' offset aligning A*cos+B*sin to sin(2π*(bar-anchor)/T)."""
    psi = math.atan2(A, B)
    ago = ((N - 1) + psi * T / (2 * math.pi)) % T
    return int(round(ago))


# ── 3-cycle script (reference template) ──────────────────────────────────────

def _generate_three_cycles(ticker: str, periods: List[int], agos: List[int],
                           anchor_dates: Optional[List[tuple]] = None) -> str:
    L1, L2, L3 = periods
    A1, A2, A3 = agos
    name = f"Cycles {ticker} - Oscillateurs sinusoidaux"

    if anchor_dates and len(anchor_dates) == 3:
        (Y1, M1, D1), (Y2, M2, D2), (Y3, M3, D3) = anchor_dates
        anchor_block = f"""\
// ============================================
// 2. ANCRES FIXES (générées par Python — ne pas modifier)
// ============================================
var int fixedAnchor1 = 0
var int fixedAnchor2 = 0
var int fixedAnchor3 = 0
if time <= timestamp({Y1}, {M1}, {D1}) + 86400000
    fixedAnchor1 := bar_index
if time <= timestamp({Y2}, {M2}, {D2}) + 86400000
    fixedAnchor2 := bar_index
if time <= timestamp({Y3}, {M3}, {D3}) + 86400000
    fixedAnchor3 := bar_index"""
    else:
        anchor_block = f"""\
// ============================================
// 2. ANCRES (mode compatibilité)
// ============================================
var int fixedAnchor1 = last_bar_index - {A1}
var int fixedAnchor2 = last_bar_index - {A2}
var int fixedAnchor3 = last_bar_index - {A3}"""

    return f"""\
//@version=6
indicator("{name}", overlay=false)

// ============================================
// 1. PARAMETRES DES CYCLES
// ============================================
len1 = input.int({L1}, "Duree cycle long (barres)", group="Cycle long")
col1 = input.color(color.orange, "Couleur", group="Cycle long")

len2 = input.int({L2}, "Duree cycle moyen (barres)", group="Cycle moyen")
col2 = input.color(color.blue, "Couleur", group="Cycle moyen")

len3 = input.int({L3}, "Duree cycle court (barres)", group="Cycle court")
col3 = input.color(color.fuchsia, "Couleur", group="Cycle court")

showOrange = input.bool(true, "Afficher fond orange (long/moyen alignes)", group="Affichage")

showGainColumn    = input.bool(true, "Afficher la colonne Gains Vert/Rouge", group="Gains Vert/Rouge")
gainLookbackYears = input.int(5, "Periode comptee (annees)", minval=1, maxval=50, group="Gains Vert/Rouge")

{anchor_block}

// ============================================
// 3. CALCUL DES SINUSOIDES
// ============================================
sine1 = math.sin(2*math.pi*(bar_index - fixedAnchor1)/len1)
sine2 = math.sin(2*math.pi*(bar_index - fixedAnchor2)/len2)
sine3 = math.sin(2*math.pi*(bar_index - fixedAnchor3)/len3)

plot(sine1, "Cycle long",  col1, 2)
plot(sine2, "Cycle moyen", col2, 2)
plot(sine3, "Cycle court", col3, 2)

hline(1,  "TOPPING",   color=color.new(color.gray, 50))
hline(0,  "",          color=color.new(color.gray, 80))
hline(-1, "BOTTOMING", color=color.new(color.gray, 50))

// ============================================
// 4. FONCTIONS
// ============================================
f_phase(_s, _sp) =>
    rising = _s > _sp
    _s > 0.5 ? "TOPPING" : _s < -0.5 ? "BOTTOMING" : rising ? "RISING" : "FALLING"

f_nextExtreme(_len, _anchor) =>
    phaseNow = (float(bar_index) - float(_anchor)) % float(_len)
    if phaseNow < 0.0
        phaseNow := phaseNow + float(_len)
    targetTop = float(_len) / 4.0
    targetBot = float(_len) * 3.0 / 4.0
    nTop = targetTop - phaseNow
    if nTop <= 0.0
        nTop := nTop + float(_len)
    nBot = targetBot - phaseNow
    if nBot <= 0.0
        nBot := nBot + float(_len)
    isTop = nTop < nBot
    nBars = isTop ? nTop : nBot
    calendarDays = nBars * 7.0 / 5.0
    futureTime = time + int(calendarDays * 86400000.0)
    icon = isTop ? "↓" : "↑"
    icon + " " + str.format_time(futureTime, "dd MMM")

phase1 = f_phase(sine1, sine1[1])
phase2 = f_phase(sine2, sine2[1])
phase3 = f_phase(sine3, sine3[1])

// ============================================
// 4. ZONES DE FOND
// ============================================
bullish1 = sine1 > sine1[1]
bullish2 = sine2 > sine2[1]
bullish3 = sine3 > sine3[1]

allBullish = bullish1 and bullish2 and bullish3
allBearish = not bullish1 and not bullish2 and not bullish3
longMedAgree = (bullish1 == bullish2) and not allBullish and not allBearish

bgZone = allBullish ? color.new(color.green, 80) : allBearish ? color.new(color.red, 80) : (showOrange and longMedAgree) ? color.new(color.orange, 80) : na
bgcolor(bgZone)

// ============================================
// 5. RENDEMENT PAR PERIODE VERTE/ROUGE + STOCKAGE POUR LE TABLEAU DE GAINS
// ============================================
zoneState = allBullish ? 1 : allBearish ? -1 : 0

var int   zoneStartBar   = na
var float zoneStartClose = na
var int   prevZoneState  = 0
var label liveLabel      = na

var array<float> zoneReturns    = array.new<float>()
var array<int>   zoneEndTimes   = array.new<int>()
var array<bool>  zoneIsGreenArr = array.new<bool>()

zoneChanged = zoneState != prevZoneState

if zoneChanged
    if prevZoneState != 0 and not na(zoneStartClose)
        ret = (close[1] - zoneStartClose) / zoneStartClose * 100
        midBar = int(math.round((zoneStartBar + (bar_index - 1)) / 2.0))
        labY = prevZoneState == 1 ? 1 : -1
        labCol = prevZoneState == 1 ? color.green : color.red
        labStyle = prevZoneState == 1 ? label.style_label_down : label.style_label_up
        label.new(midBar, labY, str.tostring(ret, "#.##") + "%", style=labStyle, color=color.new(labCol, 0), textcolor=color.white, size=size.normal)

        array.push(zoneReturns, ret)
        array.push(zoneEndTimes, time[1])
        array.push(zoneIsGreenArr, prevZoneState == 1)

    if zoneState != 0
        zoneStartBar   := bar_index
        zoneStartClose := close
    else
        zoneStartBar   := na
        zoneStartClose := na

    prevZoneState := zoneState

if zoneState != 0 and not na(zoneStartClose)
    if not na(liveLabel)
        label.delete(liveLabel)
    liveRet = (close - zoneStartClose) / zoneStartClose * 100
    midBarLive = int(math.round((zoneStartBar + bar_index) / 2.0))
    labYLive = zoneState == 1 ? 1 : -1
    labColLive = zoneState == 1 ? color.green : color.red
    labStyleLive = zoneState == 1 ? label.style_label_down : label.style_label_up
    liveLabel := label.new(midBarLive, labYLive, str.tostring(liveRet, "#.##") + "%", style=labStyleLive, color=color.new(labColLive, 0), textcolor=color.white, size=size.normal)

// ============================================
// 6. TABLEAU RECAPITULATIF (+ GAINS VERT/ROUGE)
// ============================================
if barstate.islast
    tblCols = showGainColumn ? 4 : 2
    var table t = table.new(position.top_right, tblCols, 4, bgcolor=color.new(color.black, 0), border_width=1)

    table.cell(t, 0, 0, "Cycle", text_color=color.white, text_size=size.small)
    table.cell(t, 1, 0, "Prochain", text_color=color.white, text_size=size.small)
    if showGainColumn
        table.cell(t, 2, 0, "Vert (" + str.tostring(gainLookbackYears) + "a)", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 0, "Rouge (" + str.tostring(gainLookbackYears) + "a)", text_color=color.red, text_size=size.small)

    table.cell(t, 0, 1, "Long",  text_color=col1, text_size=size.small)
    table.cell(t, 1, 1, f_nextExtreme(len1, fixedAnchor1), text_color=col1, text_size=size.small)

    table.cell(t, 0, 2, "Moyen", text_color=col2, text_size=size.small)
    table.cell(t, 1, 2, f_nextExtreme(len2, fixedAnchor2), text_color=col2, text_size=size.small)

    table.cell(t, 0, 3, "Court", text_color=col3, text_size=size.small)
    table.cell(t, 1, 3, f_nextExtreme(len3, fixedAnchor3), text_color=col3, text_size=size.small)

    if showGainColumn
        cutoffTime = time - gainLookbackYears * 365.25 * 86400000.0

        float sumGreen = 0.0
        float sumRed   = 0.0
        int   nGreen   = 0
        int   nRed     = 0

        for i = 0 to array.size(zoneReturns) - 1
            if array.get(zoneEndTimes, i) >= cutoffTime
                r   = array.get(zoneReturns, i)
                isG = array.get(zoneIsGreenArr, i)
                if isG
                    sumGreen += r
                    nGreen += 1
                else
                    sumRed += -r
                    nRed += 1

        if zoneState != 0 and not na(zoneStartClose)
            liveRetNow = (close - zoneStartClose) / zoneStartClose * 100
            if zoneState == 1
                sumGreen += liveRetNow
                nGreen += 1
            else
                sumRed += -liveRetNow
                nRed += 1

        table.cell(t, 2, 1, str.tostring(sumGreen, "#.##") + "%\\n(" + str.tostring(nGreen) + ")", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 1, str.tostring(sumRed, "#.##") + "%\\n(" + str.tostring(nRed) + ")", text_color=color.red, text_size=size.small)

// ============================================
// 7. ALERTES - ALIGNEMENT DES 3 CYCLES (J-3)
// ============================================
lookahead = 3

f_bullAt(_anchor, _len, _k) =>
    sNow  = math.sin(2*math.pi*(bar_index + _k - _anchor)/_len)
    sPrev = math.sin(2*math.pi*(bar_index + _k - 1 - _anchor)/_len)
    sNow > sPrev

bull1_0 = f_bullAt(fixedAnchor1, len1, 0)
bull2_0 = f_bullAt(fixedAnchor2, len2, 0)
bull3_0 = f_bullAt(fixedAnchor3, len3, 0)
allBull_0 = bull1_0 and bull2_0 and bull3_0
allBear_0 = (not bull1_0) and (not bull2_0) and (not bull3_0)

bull1_k = f_bullAt(fixedAnchor1, len1, lookahead)
bull2_k = f_bullAt(fixedAnchor2, len2, lookahead)
bull3_k = f_bullAt(fixedAnchor3, len3, lookahead)
allBull_k = bull1_k and bull2_k and bull3_k
allBear_k = (not bull1_k) and (not bull2_k) and (not bull3_k)

bullStartIn3 = (not allBull_0) and allBull_k
bullEndIn3   = allBull_0 and (not allBull_k)
bearStartIn3 = (not allBear_0) and allBear_k
bearEndIn3   = allBear_0 and (not allBear_k)

alertcondition(bullStartIn3, title="J-3 : debut alignement HAUSSIER", message="Alignement HAUSSIER des 3 cycles dans 3 jours")
alertcondition(bullEndIn3,   title="J-3 : fin alignement HAUSSIER",   message="Fin de l'alignement HAUSSIER des 3 cycles dans 3 jours")
alertcondition(bearStartIn3, title="J-3 : debut alignement BAISSIER", message="Alignement BAISSIER des 3 cycles dans 3 jours")
alertcondition(bearEndIn3,   title="J-3 : fin alignement BAISSIER",   message="Fin de l'alignement BAISSIER des 3 cycles dans 3 jours")
"""


# ── 2-cycle script ────────────────────────────────────────────────────────────

def _generate_two_cycles(ticker: str, periods: List[int], agos: List[int],
                         anchor_dates: Optional[List[tuple]] = None) -> str:
    L1, L2 = periods
    A1, A2 = agos
    name = f"Cycles {ticker} - Oscillateurs sinusoidaux"

    if anchor_dates and len(anchor_dates) == 2:
        (Y1, M1, D1), (Y2, M2, D2) = anchor_dates
        anchor_block = f"""\
// ============================================
// 2. ANCRES FIXES (générées par Python — ne pas modifier)
// ============================================
var int fixedAnchor1 = 0
var int fixedAnchor2 = 0
if time <= timestamp({Y1}, {M1}, {D1}) + 86400000
    fixedAnchor1 := bar_index
if time <= timestamp({Y2}, {M2}, {D2}) + 86400000
    fixedAnchor2 := bar_index"""
    else:
        anchor_block = f"""\
// ============================================
// 2. ANCRES (mode compatibilité — sans dates fixes)
// ============================================
var int fixedAnchor1 = last_bar_index - {A1}
var int fixedAnchor2 = last_bar_index - {A2}"""

    return f"""\
//@version=6
indicator("{name}", overlay=false)

// ============================================
// 1. PARAMETRES DES CYCLES
// ============================================
len1 = input.int({L1}, "Duree cycle long (barres)", group="Cycle long")
col1 = input.color(color.orange, "Couleur", group="Cycle long")

len2 = input.int({L2}, "Duree cycle court (barres)", group="Cycle court")
col2 = input.color(color.blue, "Couleur", group="Cycle court")

showGainColumn    = input.bool(true, "Afficher la colonne Gains Vert/Rouge", group="Gains Vert/Rouge")
gainLookbackYears = input.int(5, "Periode comptee (annees)", minval=1, maxval=50, group="Gains Vert/Rouge")

{anchor_block}

// ============================================
// 3. CALCUL DES SINUSOIDES
// ============================================
sine1 = math.sin(2*math.pi*(bar_index - fixedAnchor1)/len1)
sine2 = math.sin(2*math.pi*(bar_index - fixedAnchor2)/len2)

plot(sine1, "Cycle long",  col1, 2)
plot(sine2, "Cycle court", col2, 2)

hline(1,  "TOPPING",   color=color.new(color.gray, 50))
hline(0,  "",          color=color.new(color.gray, 80))
hline(-1, "BOTTOMING", color=color.new(color.gray, 50))

// ============================================
// 4. FONCTIONS
// ============================================
f_nextExtreme(_len, _anchor) =>
    phaseNow = (float(bar_index) - float(_anchor)) % float(_len)
    if phaseNow < 0.0
        phaseNow := phaseNow + float(_len)
    targetTop = float(_len) / 4.0
    targetBot = float(_len) * 3.0 / 4.0
    nTop = targetTop - phaseNow
    if nTop <= 0.0
        nTop := nTop + float(_len)
    nBot = targetBot - phaseNow
    if nBot <= 0.0
        nBot := nBot + float(_len)
    isTop = nTop < nBot
    nBars = isTop ? nTop : nBot
    calendarDays = nBars * 7.0 / 5.0
    futureTime = time + int(calendarDays * 86400000.0)
    icon = isTop ? "↓" : "↑"
    icon + " " + str.format_time(futureTime, "dd MMM")

// ============================================
// 4. ZONES DE FOND
// ============================================
bullish1 = sine1 > sine1[1]
bullish2 = sine2 > sine2[1]

allBullish = bullish1 and bullish2
allBearish = not bullish1 and not bullish2

bgZone = allBullish ? color.new(color.green, 80) : allBearish ? color.new(color.red, 80) : na
bgcolor(bgZone)

// ============================================
// 5. RENDEMENT PAR PERIODE VERTE/ROUGE
// ============================================
zoneState = allBullish ? 1 : allBearish ? -1 : 0

var int   zoneStartBar   = na
var float zoneStartClose = na
var int   prevZoneState  = 0
var label liveLabel      = na

var array<float> zoneReturns    = array.new<float>()
var array<int>   zoneEndTimes   = array.new<int>()
var array<bool>  zoneIsGreenArr = array.new<bool>()

zoneChanged = zoneState != prevZoneState

if zoneChanged
    if prevZoneState != 0 and not na(zoneStartClose)
        ret = (close[1] - zoneStartClose) / zoneStartClose * 100
        midBar = int(math.round((zoneStartBar + (bar_index - 1)) / 2.0))
        labY = prevZoneState == 1 ? 1 : -1
        labCol = prevZoneState == 1 ? color.green : color.red
        labStyle = prevZoneState == 1 ? label.style_label_down : label.style_label_up
        label.new(midBar, labY, str.tostring(ret, "#.##") + "%", style=labStyle, color=color.new(labCol, 0), textcolor=color.white, size=size.normal)
        array.push(zoneReturns, ret)
        array.push(zoneEndTimes, time[1])
        array.push(zoneIsGreenArr, prevZoneState == 1)
    if zoneState != 0
        zoneStartBar   := bar_index
        zoneStartClose := close
    else
        zoneStartBar   := na
        zoneStartClose := na
    prevZoneState := zoneState

if zoneState != 0 and not na(zoneStartClose)
    if not na(liveLabel)
        label.delete(liveLabel)
    liveRet = (close - zoneStartClose) / zoneStartClose * 100
    midBarLive = int(math.round((zoneStartBar + bar_index) / 2.0))
    labYLive = zoneState == 1 ? 1 : -1
    labColLive = zoneState == 1 ? color.green : color.red
    labStyleLive = zoneState == 1 ? label.style_label_down : label.style_label_up
    liveLabel := label.new(midBarLive, labYLive, str.tostring(liveRet, "#.##") + "%", style=labStyleLive, color=color.new(labColLive, 0), textcolor=color.white, size=size.normal)

// ============================================
// 6. TABLEAU RECAPITULATIF
// ============================================
if barstate.islast
    tblCols = showGainColumn ? 4 : 2
    var table t = table.new(position.top_right, tblCols, 3, bgcolor=color.new(color.black, 0), border_width=1)

    table.cell(t, 0, 0, "Cycle", text_color=color.white, text_size=size.small)
    table.cell(t, 1, 0, "Prochain", text_color=color.white, text_size=size.small)
    if showGainColumn
        table.cell(t, 2, 0, "Vert (" + str.tostring(gainLookbackYears) + "a)", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 0, "Rouge (" + str.tostring(gainLookbackYears) + "a)", text_color=color.red, text_size=size.small)

    table.cell(t, 0, 1, "Long",  text_color=col1, text_size=size.small)
    table.cell(t, 1, 1, f_nextExtreme(len1, fixedAnchor1), text_color=col1, text_size=size.small)
    table.cell(t, 0, 2, "Court", text_color=col2, text_size=size.small)
    table.cell(t, 1, 2, f_nextExtreme(len2, fixedAnchor2), text_color=col2, text_size=size.small)

    if showGainColumn
        cutoffTime = time - gainLookbackYears * 365.25 * 86400000.0
        float sumGreen = 0.0
        float sumRed   = 0.0
        int   nGreen   = 0
        int   nRed     = 0
        for i = 0 to array.size(zoneReturns) - 1
            if array.get(zoneEndTimes, i) >= cutoffTime
                r   = array.get(zoneReturns, i)
                isG = array.get(zoneIsGreenArr, i)
                if isG
                    sumGreen += r
                    nGreen += 1
                else
                    sumRed += -r
                    nRed += 1
        if zoneState != 0 and not na(zoneStartClose)
            liveRetNow = (close - zoneStartClose) / zoneStartClose * 100
            if zoneState == 1
                sumGreen += liveRetNow
                nGreen += 1
            else
                sumRed += -liveRetNow
                nRed += 1
        table.cell(t, 2, 1, str.tostring(sumGreen, "#.##") + "%\\n(" + str.tostring(nGreen) + ")", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 1, str.tostring(sumRed,   "#.##") + "%\\n(" + str.tostring(nRed)   + ")", text_color=color.red,   text_size=size.small)

// ============================================
// 7. ALERTES (J-3)
// ============================================
lookahead = 3

f_bullAt(_anchor, _len, _k) =>
    sNow  = math.sin(2*math.pi*(bar_index + _k - _anchor)/_len)
    sPrev = math.sin(2*math.pi*(bar_index + _k - 1 - _anchor)/_len)
    sNow > sPrev

bull1_0 = f_bullAt(fixedAnchor1, len1, 0)
bull2_0 = f_bullAt(fixedAnchor2, len2, 0)
allBull_0 = bull1_0 and bull2_0
allBear_0 = (not bull1_0) and (not bull2_0)

bull1_k = f_bullAt(fixedAnchor1, len1, lookahead)
bull2_k = f_bullAt(fixedAnchor2, len2, lookahead)
allBull_k = bull1_k and bull2_k
allBear_k = (not bull1_k) and (not bull2_k)

alertcondition((not allBull_0) and allBull_k, title="J-3 : debut alignement HAUSSIER", message="Alignement HAUSSIER des 2 cycles dans 3 jours")
alertcondition(allBull_0 and (not allBull_k),  title="J-3 : fin alignement HAUSSIER",  message="Fin de l'alignement HAUSSIER des 2 cycles dans 3 jours")
alertcondition((not allBear_0) and allBear_k,  title="J-3 : debut alignement BAISSIER", message="Alignement BAISSIER des 2 cycles dans 3 jours")
alertcondition(allBear_0 and (not allBear_k),  title="J-3 : fin alignement BAISSIER",  message="Fin de l'alignement BAISSIER des 2 cycles dans 3 jours")
"""


# ── 1-cycle script ────────────────────────────────────────────────────────────

def _generate_single_cycle(ticker: str, period: int, ago: int,
                           anchor_date: Optional[tuple] = None) -> str:
    name = f"Cycles {ticker} - Oscillateurs sinusoidaux"

    if anchor_date:
        Y1, M1, D1 = anchor_date
        anchor_block = f"""\
// ============================================
// 2. ANCRE FIXE (générée par Python — ne pas modifier)
// ============================================
var int fixedAnchor1 = 0
if time <= timestamp({Y1}, {M1}, {D1}) + 86400000
    fixedAnchor1 := bar_index"""
    else:
        anchor_block = f"""\
// ============================================
// 2. ANCRE (mode compatibilité)
// ============================================
var int fixedAnchor1 = last_bar_index - {ago}"""

    return f"""\
//@version=6
indicator("{name}", overlay=false)

// ============================================
// 1. PARAMETRES DU CYCLE
// ============================================
len1 = input.int({period}, "Duree du cycle (barres)")
col1 = input.color(color.orange, "Couleur")

showGainColumn    = input.bool(true, "Afficher la colonne Gains Vert/Rouge", group="Gains Vert/Rouge")
gainLookbackYears = input.int(5, "Periode comptee (annees)", minval=1, maxval=50, group="Gains Vert/Rouge")

{anchor_block}

// ============================================
// 3. CALCUL DE LA SINUSOIDE
// ============================================
sine1 = math.sin(2*math.pi*(bar_index - fixedAnchor1)/len1)

plot(sine1, "Cycle", col1, 2)

hline(1,  "TOPPING",   color=color.new(color.gray, 50))
hline(0,  "",          color=color.new(color.gray, 80))
hline(-1, "BOTTOMING", color=color.new(color.gray, 50))

// ============================================
// 4. FONCTIONS
// ============================================
f_nextExtreme(_len, _anchor) =>
    phaseNow = (float(bar_index) - float(_anchor)) % float(_len)
    if phaseNow < 0.0
        phaseNow := phaseNow + float(_len)
    targetTop = float(_len) / 4.0
    targetBot = float(_len) * 3.0 / 4.0
    nTop = targetTop - phaseNow
    if nTop <= 0.0
        nTop := nTop + float(_len)
    nBot = targetBot - phaseNow
    if nBot <= 0.0
        nBot := nBot + float(_len)
    isTop = nTop < nBot
    nBars = isTop ? nTop : nBot
    calendarDays = nBars * 7.0 / 5.0
    futureTime = time + int(calendarDays * 86400000.0)
    icon = isTop ? "↓" : "↑"
    icon + " " + str.format_time(futureTime, "dd MMM")

// ============================================
// 4. ZONES DE FOND
// ============================================
bullish1 = sine1 > sine1[1]
bgZone = bullish1 ? color.new(color.green, 80) : color.new(color.red, 80)
bgcolor(bgZone)

// ============================================
// 5. RENDEMENT PAR PERIODE VERTE/ROUGE
// ============================================
zoneState = bullish1 ? 1 : -1

var int   zoneStartBar   = na
var float zoneStartClose = na
var int   prevZoneState  = 0
var label liveLabel      = na

var array<float> zoneReturns    = array.new<float>()
var array<int>   zoneEndTimes   = array.new<int>()
var array<bool>  zoneIsGreenArr = array.new<bool>()

zoneChanged = zoneState != prevZoneState

if zoneChanged
    if not na(zoneStartClose)
        ret = (close[1] - zoneStartClose) / zoneStartClose * 100
        midBar = int(math.round((zoneStartBar + (bar_index - 1)) / 2.0))
        labY = prevZoneState == 1 ? 1 : -1
        labCol = prevZoneState == 1 ? color.green : color.red
        labStyle = prevZoneState == 1 ? label.style_label_down : label.style_label_up
        label.new(midBar, labY, str.tostring(ret, "#.##") + "%", style=labStyle, color=color.new(labCol, 0), textcolor=color.white, size=size.normal)
        array.push(zoneReturns, ret)
        array.push(zoneEndTimes, time[1])
        array.push(zoneIsGreenArr, prevZoneState == 1)
    zoneStartBar   := bar_index
    zoneStartClose := close
    prevZoneState  := zoneState

if not na(zoneStartClose)
    if not na(liveLabel)
        label.delete(liveLabel)
    liveRet = (close - zoneStartClose) / zoneStartClose * 100
    midBarLive = int(math.round((zoneStartBar + bar_index) / 2.0))
    labYLive = zoneState == 1 ? 1 : -1
    labColLive = zoneState == 1 ? color.green : color.red
    labStyleLive = zoneState == 1 ? label.style_label_down : label.style_label_up
    liveLabel := label.new(midBarLive, labYLive, str.tostring(liveRet, "#.##") + "%", style=labStyleLive, color=color.new(labColLive, 0), textcolor=color.white, size=size.normal)

// ============================================
// 6. TABLEAU RECAPITULATIF
// ============================================
if barstate.islast
    tblCols = showGainColumn ? 4 : 2
    var table t = table.new(position.top_right, tblCols, 2, bgcolor=color.new(color.black, 0), border_width=1)
    table.cell(t, 0, 0, "Cycle", text_color=color.white, text_size=size.small)
    table.cell(t, 1, 0, "Prochain", text_color=color.white, text_size=size.small)
    if showGainColumn
        table.cell(t, 2, 0, "Vert (" + str.tostring(gainLookbackYears) + "a)", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 0, "Rouge (" + str.tostring(gainLookbackYears) + "a)", text_color=color.red, text_size=size.small)
    table.cell(t, 0, 1, str.tostring(len1) + "b", text_color=col1, text_size=size.small)
    table.cell(t, 1, 1, f_nextExtreme(len1, fixedAnchor1), text_color=col1, text_size=size.small)
    if showGainColumn
        cutoffTime = time - gainLookbackYears * 365.25 * 86400000.0
        float sumGreen = 0.0
        float sumRed   = 0.0
        int   nGreen   = 0
        int   nRed     = 0
        for i = 0 to array.size(zoneReturns) - 1
            if array.get(zoneEndTimes, i) >= cutoffTime
                r   = array.get(zoneReturns, i)
                isG = array.get(zoneIsGreenArr, i)
                if isG
                    sumGreen += r
                    nGreen += 1
                else
                    sumRed += -r
                    nRed += 1
        if not na(zoneStartClose)
            liveRetNow = (close - zoneStartClose) / zoneStartClose * 100
            if zoneState == 1
                sumGreen += liveRetNow
                nGreen += 1
            else
                sumRed += -liveRetNow
                nRed += 1
        table.cell(t, 2, 1, str.tostring(sumGreen, "#.##") + "%\\n(" + str.tostring(nGreen) + ")", text_color=color.green, text_size=size.small)
        table.cell(t, 3, 1, str.tostring(sumRed,   "#.##") + "%\\n(" + str.tostring(nRed)   + ")", text_color=color.red,   text_size=size.small)

// ============================================
// 7. ALERTES (J-3)
// ============================================
lookahead = 3

f_bullAt(_anchor, _len, _k) =>
    sNow  = math.sin(2*math.pi*(bar_index + _k - _anchor)/_len)
    sPrev = math.sin(2*math.pi*(bar_index + _k - 1 - _anchor)/_len)
    sNow > sPrev

bull1_0 = f_bullAt(fixedAnchor1, len1, 0)
bull1_k = f_bullAt(fixedAnchor1, len1, lookahead)

alertcondition((not bull1_0) and bull1_k, title="J-3 : debut phase HAUSSIERE", message="Phase HAUSSIERE du cycle dans 3 jours")
alertcondition(bull1_0 and (not bull1_k),  title="J-3 : fin phase HAUSSIERE",  message="Fin de la phase HAUSSIERE du cycle dans 3 jours")
"""


# ── Public entry point ────────────────────────────────────────────────────────

def generate_pinescript(
    ticker: str,
    periods: List[int],
    ago_values: List[int],
    anchor_times: Optional[List[int]] = None,  # Unix ms timestamps for each cycle anchor
) -> str:
    """Generate Pine Script for 1, 2 or 3 cycles.

    anchor_times: list of Unix timestamps in milliseconds for the rising zero-crossing
    of each cycle's sine wave. When provided, anchors are fixed and dates in the
    'Prochain' table count down correctly as new bars are added.
    """
    def _ts_to_ymd(ts_ms: int) -> tuple:
        import datetime
        d = datetime.datetime.utcfromtimestamp(ts_ms / 1000)
        return (d.year, d.month, d.day)

    if anchor_times:
        dates = [_ts_to_ymd(ts) for ts in anchor_times]
    else:
        dates = None

    n = len(periods)
    if n == 1:
        return _generate_single_cycle(ticker, periods[0], ago_values[0],
                                      anchor_date=dates[0] if dates else None)
    if n == 2:
        return _generate_two_cycles(ticker, periods, ago_values,
                                    anchor_dates=dates)
    if n == 3:
        return _generate_three_cycles(ticker, periods, ago_values,
                                      anchor_dates=dates)
    raise ValueError("Only 1, 2 or 3 cycles are supported")
