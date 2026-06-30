from __future__ import annotations

APP_NAME = "MAHAD"
HELP_TEXT = ("First steps:\n"
             "  1. Add a symbol (a US ticker like AAPL, or BTC/USD).\n"
             "  2. Click a watchlist row to make it the active chart.\n"
             "  3. Open Indicators to overlay SMA / EMA / RSI.\n"
             "  4. New Alert -> arm a one-shot alert.\n"
             "  5. New Order -> place a simulated order; Portfolio and Risk track "
             "it live.\n"
             "  6. Shortcuts: Ctrl+N order · Ctrl+Shift+A alert · Ctrl+K add "
             "symbol ·\n     Ctrl+I indicators · Ctrl+1/2/3 timeframe · "
             "Ctrl+E trades CSV ·\n     Ctrl+Shift+E value-history CSV · "
             "Ctrl+Shift+P command palette · F1 help.")
HELP_CONTEXT = ("Market data: stocks - Finnhub live quotes (free key) and "
                "Tiingo daily history with dividends + splits (free key); "
                "intraday stock bars are sampled from live quotes, not "
                "exchange aggregates. Crypto - Kraken public market data, "
                "keyless. Market context: US Treasury par yield curve + "
                "2s10s spread (US Treasury, keyless) · crypto Fear & Greed "
                "(data from alternative.me, keyless) · VIX (FRED series "
                "VIXCLS - needs a free key in .env; the tile says so until "
                "one is set). This product uses the FRED API but is not "
                "endorsed or certified by the Federal Reserve Bank of St. "
                "Louis. VIX data are copyright Cboe.")
HELP_METHODOLOGY = (
    "Methodology. The risk analytics run on trading-day returns of the held "
    "assets - today's weights over a 250-day window, cash at zero, annualised "
    "with sqrt(252). They cover historical and parametric VaR, Expected "
    "Shortfall, a Kupiec/Basel backtest, beta vs SPY, Sharpe and Sortino, EWMA "
    "volatility, correlation, concentration, and component VaR. Exposure, "
    "volatility, and max drawdown above sit on a separate wall-clock 365 basis.")
HELP_IDENTITY = ("MAHAD · a desktop market-risk workstation on live market "
                 "data")

# Colour tokens
BG = "#0A0B0D"            # app background, near-black
SURFACE = "#15171B"       # elevated cards / panels
NESTED = "#1C1F24"        # nested / hover / input surface
HAIRLINE = "rgba(255,255,255,0.07)"
DIVIDER = "rgba(255,255,255,0.12)"

TEXT_1 = "rgba(255,255,255,0.92)"
TEXT_2 = "rgba(255,255,255,0.58)"
TEXT_3 = "rgba(255,255,255,0.50)"   # raised from 0.36 for WCAG AA
TEXT_3_DESIGN = "rgba(255,255,255,0.36)"   # original design value

ACCENT = "#4C8DFF"
ACCENT_SOFT = "rgba(76,141,255,0.14)"
ACCENT_LINE = "rgba(76,141,255,0.30)"
ACCENT_FILL = "#2563EB"  # filled primaries only - white label clears AA

# Passive selected states are tonal; filled primaries carry a near-black label.
TONAL_FILL = "#3A4150"            # selected segment fill
TONAL_LABEL = "#EAF0FA"
TOOLWORK_BORDER = "#3A4150"       # workspace-tier toolbar button border
TOOLWORK_LABEL = "#C9D2E0"
NEUTRAL_DOT = "#8A93A5"           # market-closed dot
ON_FILL = "#0A0B0D"               # label on accent and red fills
TAB_RULE = "rgba(255,255,255,0.22)"
TABLE_HEAD_BAND = "rgba(0,0,0,0.22)"
ZEBRA = "rgba(255,255,255,0.028)"       # even-row lift
# solid equivalents - the design's white-alpha tints vanish on near-black
ENTRY_BASE = "#161A20"                  # == ROW_SOLID
ENTRY_ALT = "#23272C"                   # 0.055 white blended over ENTRY_BASE
TD_LINE = "rgba(255,255,255,0.04)"

GREEN = "#3FB950"         # live / up
AMBER = "#D9A521"         # stale / warning
RED = "#F85149"           # down / loss
GREEN_SOFT = "rgba(63,185,80,0.12)"
AMBER_SOFT = "rgba(217,165,33,0.12)"
RED_SOFT = "rgba(248,81,73,0.12)"

PRICE = "rgba(255,255,255,0.90)"
GRID = "rgba(255,255,255,0.05)"
SMA_COLOR = "#6E8FBF"
EMA_COLOR = "#A682C0"
RSI_COLOR = "#9AA4B2"

# Liquid Glass tokens
GLASS_TINT = (60, 67, 82)           # fixed cool tint
GLASS_A_HI = 0.62                    # chrome fill opacity
GLASS_A_LO = 0.52
RIM = "rgba(255,255,255,0.20)"       # specular top rim
RIM_SOFT = "rgba(255,255,255,0.05)"
PLOT = "#0C0E12"                     # chart plot area - solid deep
ROW_SOLID = "#161A20"                # near-solid watchlist / alert row backing
SCRIM = "rgba(6,7,9,0.62)"           # static dimmed modal scrim
POPOVER_FILL = ("qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                " stop:0 rgba(28,31,37,0.985), stop:1 rgba(20,22,27,0.985))")

# Radius / spacing / type
R_CARD = 16       # floating layers: dialogs, popover, toast
R_DOCK = 12  # docked cards
R_CTRL = 10
R_INPUT = 12
R_ATOM = 6  # interior atoms: row highlights, chips
R_PILL = 999      # kept for reference; Qt squares a radius over half the box

S1, S2, S3, S4, S5, S6, S8, S10 = 4, 8, 12, 16, 20, 24, 32, 40

# Apple fonts load only if present; otherwise the fallbacks
FONT_DISPLAY = '"SF Pro Display", "Inter", "Segoe UI", "Helvetica Neue", sans-serif'   # >= 20pt
FONT_SANS = '"SF Pro Text", "Inter", "Segoe UI", "Helvetica Neue", sans-serif'         # <= 19pt
FONT_MONO = '"SF Mono", "IBM Plex Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace'
FONT_SERIF = '"New York", "Georgia", "Times New Roman", serif'                          # editorial only

# fallback lists for QFont.setFamilies
_FAMILIES_SANS = ["SF Pro Text", "Inter", "Segoe UI", "Helvetica Neue", "Arial"]
_FAMILIES_MONO = ["SF Mono", "IBM Plex Mono", "Cascadia Code", "Consolas", "DejaVu Sans Mono"]


def glass_fill(a_hi: float = GLASS_A_HI, a_lo: float = GLASS_A_LO) -> str:
    r, g, b = GLASS_TINT
    return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 rgba({r},{g},{b},{a_hi}), stop:1 rgba({r},{g},{b},{a_lo}))")


def drop_shadow(target, blur: int = 40, dy: int = 18, alpha: int = 170):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    eff = QGraphicsDropShadowEffect(target)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha))
    return eff


def stylesheet() -> str:
    gfill = glass_fill()
    gfill_soft = glass_fill(0.55, 0.48)
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT_1};
        font-family: {FONT_SANS};
        font-size: 13px;
    }}
    /* labels + checkboxes are transparent so text never paints an opaque box
 on a glass/near-solid surface; object-named labels with their own background
 (Badge / Pill* / Stat*) override this more-specific-selector-wins. */
    QLabel, QCheckBox {{ background: transparent; }}
    QToolTip {{
        background: {SURFACE};
        color: {TEXT_2};
        border: 1px solid {DIVIDER};
        border-radius: {R_CTRL}px;
        padding: 8px 12px;
    }}

    /* ---- elevated panels (surface + hairline; elevation via border) ---- */
    QFrame#Panel {{
        background: {SURFACE};
        border: 1px solid {HAIRLINE};
        border-radius: {R_DOCK}px;     /* docked card */
    }}
    QWidget#PanelHead {{ background: transparent; border-bottom: 1px solid {HAIRLINE}; }}
    /* transparent so the rounded #Panel card shows through, not an opaque box */
    QWidget#WlAddBox {{ background: transparent; }}
    /* the rows sit on the near-solid wrap; the panel stays SURFACE */
    QWidget#WlRowsHost {{ background: {ROW_SOLID}; border-radius: 8px; }}
    QLabel#PanelTitle {{ font-size: 16px; font-weight: 600; color: {TEXT_1}; }}
    QLabel#Kicker {{
        font-family: {FONT_MONO}; font-size: 11px; color: {TEXT_3};
        letter-spacing: 1px;
    }}

    /* ---- Liquid Glass chrome surfaces (frosted; static impression) ---- */
    QFrame#Glass {{
        background: {gfill};
        border: 1px solid {HAIRLINE};
        border-top: 1px solid {RIM};
        border-radius: {R_DOCK}px;     /* DOCKED chrome: 12px, no glow (radius=elevation) */
    }}
    /* the edge-to-edge top bar - full width, SQUARE corners so the
 window controls (the Close X) reach the true top-right corner; a single
 bottom hairline divides it from the body (no side/top border, no radius). */
    QFrame#ChromeHeader {{
        background: {gfill};
        border: none;
        border-bottom: 1px solid {HAIRLINE};
        border-radius: 0;
    }}
    /* the thin top chrome strip (drag handle; hairline bottom) */
    QFrame#ChromeStrip {{ background: transparent; }}
        QFrame#GlassSoft {{
        background: {gfill_soft};
        border: 1px solid {HAIRLINE};
        border-top: 1px solid {RIM_SOFT};
        border-radius: {R_DOCK}px;
    }}
    /* solid deep chart surround - data stays crisp (NEVER translucent) */
    QFrame#PlotCard {{
        background: {PLOT};
        border: 1px solid {HAIRLINE};
        border-radius: {R_DOCK}px;     /* docked card */
    }}
    /* near-solid backing under dense numeric rows (atom-tier rounding) */
    QFrame#RowWrap {{ background: {ROW_SOLID}; border-radius: 8px; }}
    /* bottom-dock content panels are transparent so the frosted dock pane shows
 behind the near-solid rows/tables (and empty-state messages sit on glass). */
    QWidget#DockPanel {{ background: transparent; }}

    /* ---- text tiers + mono data ---- */
    QLabel[tier="2"] {{ color: {TEXT_2}; }}
    QLabel[tier="3"] {{ color: {TEXT_3}; }}
    QLabel[mono="true"] {{ font-family: {FONT_MONO}; }}

    /* ---- toolbar ---- */
    QToolBar {{ background: {BG}; border: none; border-bottom: 1px solid {HAIRLINE};
               spacing: {S1}px; padding: 6px {S4}px; }}
    QToolBar QToolButton {{
        color: {TEXT_2}; background: transparent; border: 1px solid transparent;
        border-radius: {R_CTRL}px; padding: 6px 10px; font-size: 12px;
    }}
    QToolBar QToolButton:hover {{ background: {NESTED}; color: {TEXT_1}; }}
    QToolBar QToolButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT};
                                    border: 1px solid {ACCENT_LINE}; }}
    QToolBar QToolButton:disabled {{ color: {TEXT_3}; }}
    QToolBar::separator {{ background: {HAIRLINE}; width: 1px; margin: 6px 4px; }}

    /* ---- inputs ---- */
    QLineEdit {{
        background: {NESTED}; color: {TEXT_1};
        border: 1px solid {HAIRLINE}; border-radius: {R_INPUT}px;
        padding: 8px {S3}px; selection-background-color: {ACCENT_FILL};
    }}
    QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
    QLineEdit[error="true"] {{ border: 1px solid {RED}; }}

    /* ---- combo box (alert condition / direction) ---- */
    QComboBox {{
        background: {NESTED}; color: {TEXT_1};
        border: 1px solid {HAIRLINE}; border-radius: {R_INPUT}px;
        padding: 7px {S3}px; min-height: 18px;
    }}
    QComboBox:focus {{ border: 1px solid {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE}; color: {TEXT_1};
        border: 1px solid {DIVIDER}; border-radius: {R_CTRL}px;
        selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT_1};
        outline: none;
    }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {NESTED}; color: {TEXT_1};
        border: 1px solid {HAIRLINE}; border-radius: {R_CTRL}px;
        padding: 7px {S4}px; font-size: 13px; font-weight: 500;
    }}
    QPushButton:hover {{ border: 1px solid {DIVIDER}; }}
    /* a blocked action must LOOK blocked - dim fill + dim label */
    QPushButton:disabled {{ color: rgba(255,255,255,0.32);
                            background: rgba(255,255,255,0.04);
                            border: 1px solid {HAIRLINE}; }}
    QPushButton[variant="primary"] {{ background: {ACCENT_FILL}; color: #ffffff;
                                      border: 1px solid {ACCENT_FILL}; font-weight: 600; }}
    QPushButton[variant="primary"]:disabled {{ background: rgba(255,255,255,0.06);
                                               color: {TEXT_3}; border: 1px solid {HAIRLINE}; }}
    QPushButton[variant="ghost"] {{ background: transparent; color: {TEXT_2};
                                    border: 1px solid transparent; }}
    QPushButton[variant="ghost"]:hover {{ color: {TEXT_1}; background: {NESTED}; }}

    /* ---- period stepper (QSpinBox) ---- */
    QSpinBox {{
        background: {NESTED}; color: {TEXT_1};
        border: 1px solid {HAIRLINE}; border-radius: {R_CTRL}px;
        padding: 4px 10px; font-family: {FONT_MONO}; font-size: 13px;
        min-width: 64px; max-width: 84px;
    }}
    QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
    /* NoButtons is set in code: the raw up/down strip is removed so the field
 is one cleanly-rounded mono box; these rules keep any residual buttons invisible. */
    QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
    QDoubleSpinBox {{
        background: {NESTED}; color: {TEXT_1};
        border: 1px solid {HAIRLINE}; border-radius: {R_CTRL}px;
        padding: 3px 6px; font-family: {FONT_MONO}; min-width: 84px;
    }}
    QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}

    /* ---- dock + scrollbar ---- */
    QDockWidget {{ titlebar-close-icon: none; color: {TEXT_2}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {NESTED}; border-radius: 4px; min-height: 24px; }}
    /* both orientations themed; sub-controls flat dark */
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {NESTED}; border-radius: 4px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---- bottom-dock tab bar (glass chrome) ---- */
    QTabWidget#DockTabs::pane {{
        border: 1px solid {HAIRLINE}; border-radius: {R_DOCK}px;
        background: {gfill_soft}; top: -1px;
    }}
    QTabWidget#DockTabs > QTabBar {{ qproperty-drawBase: 0; }}
    QTabWidget#DockTabs > QTabBar::tab {{
        background: transparent; color: {TEXT_2};
        padding: 7px 16px; margin-right: 2px;
        border-top: 2px solid transparent;
        font-size: 13px; font-weight: 500;
    }}
    QTabWidget#DockTabs > QTabBar::tab:selected {{
        color: {TEXT_1}; font-weight: 600;
        border-top: 2px solid transparent;       /* the accent indicator is
 now a FIXED-WIDTH painted bar in
 _DockTabBar (consistent size on
 every tab); */
        background: transparent;
    }}
    QTabWidget#DockTabs > QTabBar::tab:disabled {{ color: {TEXT_3}; }}

    /* ---- alert surfaces ---- */
    #AlertDialog {{
        background: {gfill};
        border: 1px solid {DIVIDER};
        border-radius: {R_CARD}px;
    }}
    QFrame#Toast {{
        background: {gfill};
        border: 1px solid rgba(255,255,255,0.09);
        border-top: 1px solid {RIM};
        border-radius: {R_CARD}px;
    }}
    QSplitter::handle {{
        background: transparent;               /* the 6px gutter stays quiet */
    }}
    QSplitter::handle:horizontal {{
        margin: 0 2px;                         /* a QUIET 2px hairline in the */
        background: {HAIRLINE};                /* 6px gutter - matches the app's dividers, */
        border-radius: 1px;                    /* no longer a stray white line */
    }}
    QSplitter::handle:vertical {{
        margin: 2px 0;
        background: {HAIRLINE};
        border-radius: 1px;
    }}
    QSplitter::handle:hover {{
        background: {DIVIDER};                  /* a clear hover lift keeps the grab */
    }}
    QFrame#AlertEntry {{
        background: {ENTRY_BASE};              /* each */
        border: 1px solid {DIVIDER};           /* alert is a discrete bordered entry */
        border-radius: {R_ATOM}px;             /* on the pane - the export's */
    }}                                         /* GAlertsPanel row language */
    QFrame#AlertEntry[zebra="on"] {{
        background: {ENTRY_ALT};               /* the alternating lift (solid - see
 the ENTRY_BASE token note) */
    }}
    QLabel#FieldLabel {{
        font-family: {FONT_MONO}; font-size: 11px; color: {TEXT_3};
        letter-spacing: 1px;
    }}
    /* unread-fired count badge (ACCENT_FILL so white clears AA) + the neutral armed-count chip */
    QLabel#TabCount {{
        background: {ACCENT_FILL}; color: #ffffff;    /* blue count badge
 (white 5.17:1 AA); */
        min-width: 16px; min-height: 16px;
        border-radius: 8px; padding: 0 5px;
        font-family: {FONT_MONO}; font-size: 11px; font-weight: 600;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#Badge {{
        background: {ACCENT_FILL}; color: #ffffff;
        min-width: 18px; min-height: 18px;
        border-radius: 9px; padding: 0 5px;
        font-family: {FONT_MONO}; font-size: 11px; font-weight: 600;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#BadgePaused {{
        background: {AMBER}; color: #1a1405;
        border-radius: 9px; padding: 1px 6px;
        font-family: {FONT_MONO}; font-size: 11px; font-weight: 600;
    }}
    /* armed = the quiet RESTING state (hairline + TEXT_3, no fill); green spends
 only on the fired EVENT - colour is spent, not worn. */
    QLabel#PillArmed {{
        color: {TEXT_2}; background: transparent;             /* one ink scale */
        border: 1px solid {HAIRLINE}; border-radius: {R_ATOM}px;   /* one radius scale */
        padding: 0 10px; font-family: {FONT_MONO}; font-size: 11px;
    }}
    QLabel#PillFired {{
        color: {GREEN}; background: {GREEN_SOFT};
        border: 1px solid rgba(63,185,80,0.40); border-radius: {R_ATOM}px;   /* */
        padding: 0 10px; font-family: {FONT_MONO}; font-size: 11px;
    }}
    QLabel#PillPaused {{
        color: {TEXT_3}; background: rgba(255,255,255,0.05);
        border: 1px solid {HAIRLINE}; border-radius: 11px;
        padding: 0 10px; font-family: {FONT_MONO}; font-size: 11px;
    }}

    /* ---- status bar band ---- */
    QStatusBar {{ background: {SURFACE}; border-top: 1px solid {HAIRLINE}; color: {TEXT_3}; }}
    QStatusBar::item {{ border: none; }}

    /* ======== surfaces ======== */
    /* frameless glass dialog: one chrome reused by alert/order/reset */
    /* the chrome lives on the dialogs' INNER frames */
    #GlassDialog {{ background: {gfill}; border: 1px solid {DIVIDER};
                    border-top: 1px solid {RIM}; border-radius: {R_CARD}px; }}
    QLabel#DialogTitle {{ font-family: {FONT_DISPLAY}; font-size: 17px; font-weight: 600;
                          color: {TEXT_1}; background: transparent; }}
    /* destructive dialogs carry the warn state on the TITLE (the icon tiles are
 deleted; one treatment, no extra hairline) */
    QLabel#DialogTitleWarn {{ font-family: {FONT_DISPLAY}; font-size: 17px; font-weight: 600;
                              color: {AMBER}; background: transparent; }}
    QPushButton#DialogClose {{ background: transparent; color: {TEXT_3}; border: none;
                               border-radius: {R_CTRL}px; padding: 2px 7px; font-size: 15px; }}
    QPushButton#DialogClose:hover {{ background: {NESTED}; color: {TEXT_1}; }}

    /* portfolio header stat block (g-stat) - SF Mono values */
    QLabel#StatLabel {{ color: {TEXT_3}; font-size: 11px; background: transparent; }}
    QLabel#StatValue {{ font-family: {FONT_MONO}; font-size: 18px; color: {TEXT_1}; background: transparent; }}
    QLabel#StatValuePos {{ font-family: {FONT_MONO}; font-size: 18px; color: {GREEN}; background: transparent; }}
    QLabel#StatValueNeg {{ font-family: {FONT_MONO}; font-size: 18px; color: {RED}; background: transparent; }}

    /* positions / trades data tables (g-table) - mono tabular, right-aligned numerics */
    QTableWidget#DataTable {{
        background: {PLOT}; gridline-color: transparent; outline: none;
        border: 1px solid {HAIRLINE}; border-radius: {R_CTRL}px;
        color: {TEXT_1}; font-family: {FONT_MONO}; font-size: 13px;
        selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT_1};
        alternate-background-color: {ZEBRA};       /* zebra - adjacent rows never blur */
    }}
    QTableWidget#DataTable::item {{ padding: 7px 12px; border-bottom: 1px solid {TD_LINE}; }}
    QHeaderView::section {{
        background: {TABLE_HEAD_BAND}; color: {TEXT_2};    /* the distinct header band */
        font-family: {FONT_MONO}; font-size: 10px; font-weight: 500;
        letter-spacing: 0.8px;             /* the export g-table th grammar */
        padding: 6px 12px; border: none; border-bottom: 1px solid {DIVIDER};
    }}
    QTableCornerButton::section {{ background: {SURFACE}; border: none; }}

    /* ---- command palette ---- */
    QLineEdit#CmdSearch {{ font-size: 14px; }}
    QListWidget#CmdList {{
        background: {ROW_SOLID}; border: 1px solid {HAIRLINE};
        border-radius: {R_ATOM}px; color: {TEXT_1};
        font-family: {FONT_MONO}; font-size: 13px; outline: none;
        padding: 4px;
    }}
    QListWidget#CmdList::item {{ padding: 7px 10px; border-radius: 6px; color: {TEXT_2}; }}
    QListWidget#CmdList::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT_1}; }}

    /* readout / tip boxes + inline warn (export-before-clear, ticket states) */
    #ReadoutBox {{ background: {ROW_SOLID}; border: 1px solid {HAIRLINE};
                         border-radius: {R_ATOM}px; }}    /* interior atom */
    #TipBox {{ background: {NESTED}; border: 1px solid {HAIRLINE};
                     border-radius: {R_ATOM}px; }}   /* neutral, no accent spend */
    QLabel#InlineWarn {{ color: {AMBER}; font-family: {FONT_MONO}; font-size: 11.5px;
                         background: transparent; }}
    QLabel#FillOk {{ color: {GREEN}; font-family: {FONT_MONO}; font-size: 13px; font-weight: 600;
                     background: transparent; }}

    /* danger button (reset) */
    QPushButton[variant="danger"] {{ background: {RED}; color: {ON_FILL};
                                     border: 1px solid {RED}; font-weight: 600; }}
    QPushButton[variant="danger"]:disabled {{ background: rgba(255,255,255,0.06);
                                              color: {TEXT_3}; border: 1px solid {HAIRLINE}; }}

    /* ======== risk panel ======== */
    /* one continuous near-solid #161A20 data region (glass is the dock only, never
 behind numbers); status-coloured numerics render here so they clear WCAG AA. */
    QFrame#RiskBody {{ background: {ROW_SOLID}; border-radius: 12px; }}
    /* the risk-panel container widgets are transparent (scoped, so they do not
 cascade over the #RiskBody backing); labels are already transparent. */
    QWidget#RiskPanelRoot, QWidget#RiskContent, QWidget#RiskMetric,
    QWidget#RiskSparkRow, QWidget#RiskPosWrap,
    QWidget#RiskSubGroup, QWidget#CtxHead, QWidget#StressVal {{ background: transparent; }}
    QLabel#RiskMetricKicker {{ font-family: {FONT_MONO}; font-size: 11px; color: {TEXT_2};
                               letter-spacing: 1.2px; background: transparent; }}
    QLabel#RiskValue {{ font-family: {FONT_MONO}; font-size: 18px; font-weight: 600;
                        color: {TEXT_1}; background: transparent; }}
    /* the focal EXPOSURE number - one step up */
    QLabel#RiskValueBig {{ font-family: {FONT_MONO}; font-size: 22px; font-weight: 600;
                           color: {TEXT_1}; background: transparent; }}
    QLabel#RiskValueBigMuted {{ font-family: {FONT_MONO}; font-size: 22px; font-weight: 600;
                                color: {TEXT_2}; background: transparent; }}
    QLabel#RiskValueNeg {{ font-family: {FONT_MONO}; font-size: 18px; font-weight: 600;
                           color: {RED}; background: transparent; }}
    QLabel#RiskValueMuted {{ font-family: {FONT_MONO}; font-size: 18px; font-weight: 600;
                             color: {TEXT_2}; background: transparent; }}
    QLabel#RiskSub {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_2};
                      background: transparent; }}
    QLabel#RiskCaption {{ font-family: {FONT_MONO}; font-size: 10px; color: {TEXT_2};
                          background: transparent; }}
    QLabel#RiskState {{ font-family: {FONT_SANS}; font-size: 11px; color: {TEXT_2};
                        background: transparent; }}
    /* the volatility caveat: >= 11pt, wraps, never shrinks */
    QLabel#RiskCaveat {{ font-family: {FONT_SANS}; font-size: 11px; color: {TEXT_2};
                         background: transparent; }}
    /* out-of-range flag - visible copy, not hue alone */
    QLabel#RiskFlag {{ font-family: {FONT_MONO}; font-size: 10px; font-weight: 600;
                       color: {RED}; background: transparent; }}
    QLabel#RiskHint {{ font-family: {FONT_MONO}; font-size: 11px; color: {AMBER};
                       background: transparent; }}
    QLabel#RiskEmpty {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_2};
                        background: transparent; }}
    QLabel#RiskPosSym {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_2};
                         background: transparent; }}
    QLabel#RiskPosPct {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_1};
                         background: transparent; }}
    /* the MARKET CONTEXT tiles + the value-history CSV chip */
    QLabel#CtxName {{ font-family: {FONT_MONO}; font-size: 11px; color: {TEXT_2};
                      background: transparent; letter-spacing: 1.2px; }}
    QLabel#CtxVal {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_1};
                     background: transparent; }}
    QLabel#CtxValMuted {{ font-family: {FONT_MONO}; font-size: 12px; color: {TEXT_3};
                          background: transparent; }}
    /* the muted basis tag under each stress magnitude (a scenario figure, not live P&L) */
    QLabel#StressBasis {{ font-family: {FONT_MONO}; font-size: 9px; color: {TEXT_3};
                          background: transparent; letter-spacing: 0.4px; }}
    QLabel#CtxSummary {{ font-family: {FONT_MONO}; font-size: 11px; color: {TEXT_3};
                         background: transparent; }}
    QPushButton#CsvChip {{ background: transparent; border: 1px solid {DIVIDER};
                           border-radius: 6px; padding: 0; font-family: {FONT_MONO};
                           font-size: 10px; font-weight: 600; color: {TEXT_2}; }}
    QPushButton#CsvChip:hover {{ border-color: rgba(255,255,255,0.35); color: {TEXT_1}; }}
    QPushButton#CsvChip:disabled {{ color: {TEXT_3}; border-color: {HAIRLINE}; }}
    """


def apply(app) -> None:
    from PySide6.QtGui import QFont

    font = QFont()
    try:
        font.setFamilies(_FAMILIES_SANS)        # SF Pro Text -> Inter -> system
    except Exception:
        font.setFamily("Inter")
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(stylesheet())
    configure_pyqtgraph()


def configure_pyqtgraph() -> None:
    import pyqtgraph as pg
    pg.setConfigOptions(antialias=True)
    pg.setConfigOption("background", PLOT)     # solid deep plot
    pg.setConfigOption("foreground", _qcolor(TEXT_3))


def _qcolor(token: str):
    from PySide6.QtGui import QColor
    t = token.strip()
    if t.startswith("rgba"):
        nums = t[t.index("(") + 1:t.index(")")].split(",")
        r, g, b = (int(float(n)) for n in nums[:3])
        a = int(float(nums[3]) * 255) if len(nums) > 3 else 255
        return QColor(r, g, b, a)
    return QColor(t)


def price_pen():
    import pyqtgraph as pg
    return pg.mkPen(_qcolor(PRICE), width=1.8)


def sma_pen():
    import pyqtgraph as pg
    c = _qcolor(SMA_COLOR); c.setAlphaF(0.75)        # muted, secondary
    return pg.mkPen(c, width=1.3)


def ema_pen():
    import pyqtgraph as pg
    c = _qcolor(EMA_COLOR); c.setAlphaF(0.75)
    return pg.mkPen(c, width=1.3)


def rsi_pen():
    import pyqtgraph as pg
    return pg.mkPen(_qcolor(RSI_COLOR), width=1.3)  # matches the popover swatch


def guide_pen():
    import pyqtgraph as pg
    from PySide6.QtCore import Qt
    return pg.mkPen(_qcolor(DIVIDER), width=1, style=Qt.PenStyle.DashLine)


def mono_axis_font(size: int = 9):
    from PySide6.QtGui import QFont
    f = QFont()
    try:
        f.setFamilies(_FAMILIES_MONO)           # SF Mono -> IBM Plex Mono -> system
    except Exception:
        f.setFamily("IBM Plex Mono")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(size)
    return f


AA_NORMAL = 4.5            # WCAG 2.1 AA contrast floor for normal-size text


def _rgb_tuple(token: str) -> tuple:
    # alpha component, if any, is ignored
    t = token.strip()
    if t.startswith("#"):
        return (int(t[1:3], 16), int(t[3:5], 16), int(t[5:7], 16))
    if t.startswith("rgb"):
        nums = t[t.index("(") + 1:t.index(")")].split(",")
        return (int(float(nums[0])), int(float(nums[1])), int(float(nums[2])))
    raise ValueError("unparseable colour token: " + repr(token))


def _lin8(c8: float) -> float:
    c = c8 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb) -> float:
    return 0.2126 * _lin8(rgb[0]) + 0.7152 * _lin8(rgb[1]) + 0.0722 * _lin8(rgb[2])


def contrast_ratio(rgb1, rgb2) -> float:
    l1, l2 = relative_luminance(rgb1), relative_luminance(rgb2)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def composite_over(fg_rgba, bg_rgb) -> tuple:
    a = fg_rgba[3] / 255.0
    return tuple(round(fg_rgba[i] * a + bg_rgb[i] * (1.0 - a)) for i in range(3))


def aa_ink_for(bg_rgb, light: str = TEXT_1, dark: str = PLOT) -> str:
    cl = contrast_ratio(_rgb_tuple(light), bg_rgb)
    cd = contrast_ratio(_rgb_tuple(dark), bg_rgb)
    return light if cl >= cd else dark
