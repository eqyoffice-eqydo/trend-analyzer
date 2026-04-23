"""
Trend Analyzer v3
=================
Surse: Google Trends · GDELT News · Wikipedia (RO+EN) · World Bank · RSS · Reddit
Îmbunătățiri v3:
  - Google Trends: cache 1h + retry + locale en-US (funcționează mai bine pe cloud)
  - Wikipedia: încearcă ro.wikipedia.org primul, fallback en.wikipedia.org
  - GDELT: fără filtru de limbă obligatoriu (mai multe date)
  - Interpretare: viteză trend, analiza vârfurilor, context comparativ
  - Grafice: Linie / Bare / Arie / Heatmap săptămânal / Normalizat
  - RSS: surse românești extinse
"""

import time
import requests
import feedparser
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from urllib.parse import quote
import streamlit as st

try:
    from pytrends.request import TrendReq
    PYTRENDS_OK = True
except ImportError:
    PYTRENDS_OK = False

# ── Config ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trend Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.4rem; }
    .trend-score-box {
        font-size: 2.4rem; font-weight: 800; text-align: center;
        padding: 1.1rem 2rem; border-radius: 14px; margin-bottom: 1rem;
    }
    .ts-high { background:#d4edda; color:#155724; border:2px solid #c3e6cb; }
    .ts-mid  { background:#fff3cd; color:#856404; border:2px solid #ffeeba; }
    .ts-low  { background:#f8d7da; color:#721c24; border:2px solid #f5c6cb; }
    blockquote { border-left:4px solid #4e73df; padding-left:1rem; color:#333; }
</style>
""", unsafe_allow_html=True)

# ── Constante ─────────────────────────────────────────────────────────────────
REGIONS = {
    "Global":             ("",   "WLD"),
    "România (RO)":       ("RO", "ROU"),
    "Germania (DE)":      ("DE", "DEU"),
    "Franța (FR)":        ("FR", "FRA"),
    "Regatul Unit (GB)":  ("GB", "GBR"),
    "SUA (US)":           ("US", "USA"),
    "Italia (IT)":        ("IT", "ITA"),
    "Spania (ES)":        ("ES", "ESP"),
    "Polonia (PL)":       ("PL", "POL"),
}

PERIODS = {
    "Ultima lună":     ("today 1-m",  30,   1),
    "Ultimele 3 luni": ("today 3-m",  90,   3),
    "Ultimele 6 luni": ("today 6-m",  180,  6),
    "Ultimul an":      ("today 12-m", 365,  12),
    "Ultimii 2 ani":   ("today 24-m", 730,  24),
    "Ultimii 5 ani":   ("today 60-m", 1825, 60),
}

CHART_TYPES = ["📈 Linie", "📊 Bare", "🔵 Arie", "🗓️ Heatmap săptămânal", "⚖️ Normalizat (0–100)"]

RSS_FEEDS = {
    "Română": [
        ("Digi24",       "https://www.digi24.ro/rss"),
        ("HotNews",      "https://www.hotnews.ro/rss"),
        ("G4Media",      "https://www.g4media.ro/feed"),
        ("ProTV Știri",  "https://stirileprotv.ro/rss.xml"),
        ("Mediafax",     "https://www.mediafax.ro/rss/"),
        ("Ziarul Fin.",  "https://www.zf.ro/rss/"),
        ("Economica",    "https://economica.net/feed"),
        ("Libertatea",   "https://www.libertatea.ro/feed"),
        ("Adevarul",     "https://adevarul.ro/rss/articles"),
    ],
    "Engleză": [
        ("Reuters",       "https://feeds.reuters.com/reuters/topNews"),
        ("BBC",           "http://feeds.bbci.co.uk/news/rss.xml"),
        ("Al Jazeera",    "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian",  "https://www.theguardian.com/world/rss"),
        ("AP News",       "https://feeds.apnews.com/rss/topnews"),
        ("DW",            "https://rss.dw.com/rdf/rss-en-all"),
    ],
    "Toate limbile": [
        ("Digi24",    "https://www.digi24.ro/rss"),
        ("HotNews",   "https://www.hotnews.ro/rss"),
        ("G4Media",   "https://www.g4media.ro/feed"),
        ("Reuters",   "https://feeds.reuters.com/reuters/topNews"),
        ("BBC",       "http://feeds.bbci.co.uk/news/rss.xml"),
        ("AP News",   "https://feeds.apnews.com/rss/topnews"),
        ("DW",        "https://rss.dw.com/rdf/rss-en-all"),
    ],
}

WB_INDICATORS = {
    "FP.CPI.TOTL.ZG":   "Inflație (%/an)",
    "NY.GDP.MKTP.KD.ZG": "Creștere PIB (%/an)",
    "SL.UEM.TOTL.ZS":   "Șomaj (%)",
}

COLORS   = ["#4e73df","#e74a3b","#1cc88a","#f6c23e","#9b59b6","#e67e22"]
HEADERS  = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
GDELT_BASE  = "https://api.gdeltproject.org/api/v2/doc/doc"
WB_BASE     = "https://api.worldbank.org/v2"


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCȚII DE DATE (cu cache 1 oră)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_trends(keywords_t: tuple, region_code: str, timeframe: str):
    """Google Trends cu retry + cache 1h. Returnează (df, related, eroare)."""
    if not PYTRENDS_OK:
        return None, None, "pytrends nu este instalat."

    keywords = list(keywords_t)
    last_err = "Eroare necunoscută"

    for attempt in range(4):
        try:
            # retries/backoff_factor scose — incompatibile cu urllib3>=2.0
            pt = TrendReq(
                hl="en-US",
                tz=120,
                timeout=(20, 60),
                requests_args={"headers": HEADERS},
            )
            pt.build_payload(keywords[:5], cat=0,
                             timeframe=timeframe, geo=region_code, gprop="")
            df = pt.interest_over_time()
            if df.empty:
                return None, None, "Fără date pentru această combinație."
            df = df.drop(columns=["isPartial"], errors="ignore")

            time.sleep(1.5)
            related = {}
            try:
                rq = pt.related_queries()
                for kw in keywords:
                    if kw in rq and rq[kw]["top"] is not None:
                        related[kw] = rq[kw]["top"].head(6)
            except Exception:
                pass
            return df, related, None

        except Exception as exc:
            last_err = str(exc)
            wait = 4 + attempt * 3
            time.sleep(wait)

    return None, None, f"Google Trends indisponibil temporar (eroare: {last_err}). Încearcă din nou în câteva minute."


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_gdelt(keyword: str, days: int):
    """GDELT fără filtru de limbă — mai multe date la nivel global."""
    end_dt   = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days)
    sdt = start_dt.strftime("%Y%m%d%H%M%S")
    edt = end_dt.strftime("%Y%m%d%H%M%S")
    result = {}

    for mode in ["timelinevol", "timelineTone", "artlist"]:
        try:
            params = {"query": keyword, "mode": mode, "format": "json",
                      "startdatetime": sdt, "enddatetime": edt}
            if mode != "artlist":
                params["smoothing"] = 3
            else:
                params.update({"maxrecords": 15, "sort": "datedesc"})

            r = requests.get(GDELT_BASE, params=params,
                             headers=HEADERS, timeout=25)
            if r.status_code != 200 or not r.text.strip():
                continue
            js = r.json()

            if mode == "artlist":
                result["articles"] = js.get("articles", [])
                continue

            rows = []
            for series in js.get("timeline", []):
                label = series.get("series", mode)
                for item in series.get("data", []):
                    row = {"date": pd.to_datetime(item["date"]), "value": item["value"]}
                    if mode == "timelinevol":
                        row["volume"] = row.pop("value")
                    else:
                        row["series"] = label
                    rows.append(row)
            if rows:
                df = pd.DataFrame(rows)
                if mode == "timelinevol":
                    result["volume"] = df.set_index("date")
                else:
                    result["tone"] = df
        except Exception as exc:
            result[f"{mode}_error"] = str(exc)

    return result


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_wikipedia_views(keyword: str, days: int, prefer_ro: bool = False):
    """Caută în Wikipedia RO sau EN și returnează page views zilnice."""
    langs = ["ro", "en"] if prefer_ro else ["en", "ro"]

    for lang in langs:
        try:
            sr = requests.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={"action":"query","list":"search","srsearch":keyword,
                        "format":"json","srlimit":1},
                headers=HEADERS, timeout=10,
            )
            if sr.status_code != 200:
                continue
            hits = sr.json().get("query",{}).get("search",[])
            if not hits:
                continue

            title    = hits[0]["title"].replace(" ","_")
            end_dt   = datetime.utcnow()
            start_dt = end_dt - timedelta(days=days)

            vr = requests.get(
                f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
                f"/{lang}.wikipedia/all-access/all-agents"
                f"/{quote(title)}/daily"
                f"/{start_dt.strftime('%Y%m%d')}/{end_dt.strftime('%Y%m%d')}",
                headers=HEADERS, timeout=10,
            )
            if vr.status_code != 200:
                continue
            items = vr.json().get("items", [])
            if not items:
                continue

            rows = [{"date": pd.to_datetime(it["timestamp"][:8], format="%Y%m%d"),
                     "views": it["views"]} for it in items]
            df = pd.DataFrame(rows).set_index("date")
            return df, f"{title.replace('_',' ')} ({lang}.wikipedia)"
        except Exception:
            continue

    return None, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_world_bank(wb_country: str, months: int):
    end_year   = datetime.now().year
    start_year = max(end_year - max(months // 12, 3), end_year - 12)
    results = {}
    for indicator, label in WB_INDICATORS.items():
        try:
            r = requests.get(
                f"{WB_BASE}/country/{wb_country}/indicator/{indicator}",
                params={"format":"json","date":f"{start_year}:{end_year}","per_page":"20"},
                headers=HEADERS, timeout=12,
            )
            if r.status_code == 200:
                data = r.json()
                if len(data) > 1 and data[1]:
                    rows = [{"year": int(it["date"]), "value": it["value"]}
                            for it in data[1] if it.get("value") is not None]
                    if rows:
                        results[label] = pd.DataFrame(rows).sort_values("year")
        except Exception:
            pass
    return results


def _rss_variants(keyword: str) -> list:
    """Generează variante de căutare din keyword pentru matching RSS mai bun."""
    kw = keyword.strip()
    variants = [kw.lower()]
    words = kw.split()
    # Fiecare cuvânt individual >= 3 litere (exclude 'și', 'de', 'în' etc.)
    for w in words:
        w_clean = w.strip(".,!?-()").lower()
        if len(w_clean) >= 3 and w_clean not in variants:
            variants.append(w_clean)
    # Acronim auto: "Partidul AUR" → ultimul cuvânt "aur" deja prins
    # Dacă keyword e multi-cuvânt, adaugă și ultimele 2 cuvinte
    if len(words) >= 2:
        last2 = " ".join(words[-2:]).lower()
        if last2 not in variants:
            variants.append(last2)
    return variants


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_rss_news(keyword: str, lang_key: str, days: int = 30):
    feeds    = RSS_FEEDS.get(lang_key, RSS_FEEDS["Toate limbile"])
    variants = _rss_variants(keyword)
    cutoff   = datetime.now() - timedelta(days=min(days, 30))
    articles = []
    for source_name, feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                text    = (title + " " + summary).lower()
                if not any(v in text for v in variants):
                    continue
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6])
                    if pub_dt < cutoff:
                        continue
                    date_str = pub_dt.strftime("%Y-%m-%d")
                else:
                    date_str = "—"
                articles.append({"title":title,"link":entry.get("link","#"),
                                  "source":source_name,"date":date_str})
        except Exception:
            pass
    articles.sort(key=lambda x: x["date"], reverse=True)
    return articles[:25]


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_reddit(keyword: str, days: int = 30):
    try:
        r = requests.get(
            "https://www.reddit.com/search.json",
            params={"q":keyword,"sort":"new","t":"month","limit":100},
            headers={"User-Agent":"TrendAnalyzer:v3.0 (research)"},
            timeout=15,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        posts = r.json().get("data",{}).get("children",[])
        if not posts:
            return None, "Fără posturi găsite."
        cutoff = datetime.now() - timedelta(days=days)
        rows = []
        for post in posts:
            d = post.get("data",{})
            created = datetime.fromtimestamp(d.get("created_utc",0))
            if created < cutoff:
                continue
            rows.append({
                "date": created.date(),
                "title": d.get("title",""),
                "score": d.get("score",0),
                "comments": d.get("num_comments",0),
                "subreddit": d.get("subreddit",""),
                "url": f"https://reddit.com{d.get('permalink','')}",
                "upvote_ratio": d.get("upvote_ratio",0.5),
            })
        if not rows:
            return None, "Nicio postare recentă."
        return pd.DataFrame(rows), None
    except Exception as exc:
        return None, str(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# GRAFICE
# ═══════════════════════════════════════════════════════════════════════════════

def make_chart(df_dict: dict, chart_type: str, title: str,
               yaxis_title: str = "Valoare", height: int = 380):
    """
    df_dict = {label: pd.Series cu index datetime}
    chart_type = unul din CHART_TYPES
    """
    ct = chart_type

    # ── Heatmap săptămânal ──────────────────────────────────────────────────
    if "Heatmap" in ct:
        # Folosim prima serie
        label, series = list(df_dict.items())[0]
        df = series.reset_index()
        df.columns = ["date","value"]
        df["date"] = pd.to_datetime(df["date"])
        df["week"]    = df["date"].dt.isocalendar().week.astype(int)
        df["weekday"] = df["date"].dt.day_name()
        df["year"]    = df["date"].dt.year

        pivot = df.pivot_table(index="weekday", columns="week",
                               values="value", aggfunc="mean")
        days_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        pivot = pivot.reindex([d for d in days_order if d in pivot.index])

        fig = go.Figure(go.Heatmap(
            z=pivot.values,
            x=[str(c) for c in pivot.columns],
            y=pivot.index.tolist(),
            colorscale="Blues",
            hoverongaps=False,
            hovertemplate="Săpt. %{x} · %{y}<br>Valoare: %{z:.1f}<extra></extra>",
        ))
        fig.update_layout(title=f"Heatmap săptămânal: {label}",
                          xaxis_title="Săptămâna anului",
                          height=height, plot_bgcolor="#ffffff")
        return fig

    # ── Normalizat 0–100 ────────────────────────────────────────────────────
    if "Normalizat" in ct:
        fig = go.Figure()
        for i, (label, series) in enumerate(df_dict.items()):
            mn, mx = series.min(), series.max()
            norm = (series - mn) / (mx - mn + 1e-9) * 100
            fig.add_trace(go.Scatter(
                x=norm.index, y=norm.values,
                mode="lines", name=label,
                line=dict(width=2.5, color=COLORS[i % len(COLORS)]),
            ))
        fig.update_layout(title=title, yaxis_title="Scor normalizat (0–100)",
                          hovermode="x unified", height=height,
                          plot_bgcolor="#ffffff",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02))
        fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
        fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", range=[0,105])
        return fig

    # ── Linie / Arie / Bare ─────────────────────────────────────────────────
    fig = go.Figure()
    for i, (label, series) in enumerate(df_dict.items()):
        color = COLORS[i % len(COLORS)]
        if "Bare" in ct:
            fig.add_trace(go.Bar(
                x=series.index, y=series.values, name=label,
                marker_color=color, opacity=0.8,
            ))
        elif "Arie" in ct:
            fig.add_trace(go.Scatter(
                x=series.index, y=series.values,
                mode="lines", name=label, fill="tozeroy",
                line=dict(width=2, color=color),
                fillcolor=color.replace(")", ",0.15)").replace("rgb","rgba") if color.startswith("rgb") else color + "26",
            ))
        else:  # Linie
            fig.add_trace(go.Scatter(
                x=series.index, y=series.values,
                mode="lines", name=label,
                line=dict(width=2.5, color=color),
                hovertemplate=f"<b>{label}</b>: %{{y:.1f}}<extra></extra>",
            ))

    fig.update_layout(
        title=title, yaxis_title=yaxis_title,
        hovermode="x unified", height=height,
        plot_bgcolor="#ffffff", barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# TREND SCORE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trend_score(gt_df, gdelt, wiki_df, reddit_df, rss_articles, keyword):
    scores, details = [], []

    if gt_df is not None and keyword in gt_df.columns:
        vals = gt_df[keyword].values
        n = len(vals)
        if n >= 4:
            s = min(100, max(0, 50 + (vals[-n//4:].mean() - vals[:n//4].mean()) / max(vals[:n//4].mean(), 1) * 30))
        else:
            s = float(vals.mean())
        scores.append(s); details.append(f"Google Trends: **{s:.0f}/100**")

    if "volume" in gdelt and not gdelt["volume"].empty:
        vol = gdelt["volume"]["volume"]
        s = min(100, (vol.iloc[-7:].mean() / max(vol.mean(), 0.001)) * 50) if len(vol) >= 7 else 50.0
        scores.append(s); details.append(f"GDELT media: **{s:.0f}/100**")

    if wiki_df is not None and not wiki_df.empty:
        views = wiki_df["views"].values
        n = len(views)
        if n >= 4:
            s = min(100, max(0, 50 + (views[-n//4:].mean() - views[:n//4].mean()) / max(views[:n//4].mean(), 1) * 30))
        else:
            s = 50.0
        scores.append(s); details.append(f"Wikipedia: **{s:.0f}/100**")

    if reddit_df is not None and not reddit_df.empty:
        s = float(reddit_df["upvote_ratio"].mean() * 100)
        scores.append(s); details.append(f"Reddit aprobare: **{s:.0f}/100**")

    if rss_articles:
        s = min(100, len(rss_articles) * 6)
        scores.append(s); details.append(f"RSS articole ({len(rss_articles)}): **{s:.0f}/100**")

    if not scores:
        return None, []
    return round(sum(scores) / len(scores)), details


# ═══════════════════════════════════════════════════════════════════════════════
# INTERPRETARE DETALIATĂ
# ═══════════════════════════════════════════════════════════════════════════════

def build_interpretation(gt_df, gdelt, wiki_df, reddit_df, rss_articles,
                          keyword, trend_score):
    notes = []

    # ── Google Trends ─────────────────────────────────────────────────────────
    if gt_df is not None and keyword in gt_df.columns:
        vals = gt_df[keyword].values
        n    = len(vals)

        if n >= 4:
            q1_mean = vals[:n//4].mean()
            q4_mean = vals[-n//4:].mean()
            pct_change = ((q4_mean - q1_mean) / max(q1_mean, 1)) * 100

            if pct_change > 25:
                notes.append(f"📈 **Interes în creștere** (+{pct_change:.0f}%): căutările pentru *{keyword}* au crescut semnificativ față de începutul perioadei.")
            elif pct_change < -25:
                notes.append(f"📉 **Interes în scădere** ({pct_change:.0f}%): căutările pentru *{keyword}* s-au redus față de începutul perioadei.")
            else:
                notes.append(f"➡️ **Interes stabil** (variație {pct_change:+.0f}%): căutările rămân relativ constante.")

        # Viteză (ultima săptămână vs săptămâna anterioară)
        if n >= 14:
            last_week = vals[-7:].mean()
            prev_week = vals[-14:-7].mean()
            velocity  = ((last_week - prev_week) / max(prev_week, 1)) * 100
            if velocity > 30:
                notes.append(f"⚡ **Accelerare puternică** (+{velocity:.0f}% față de săptămâna anterioară): trendului i s-a dat un nou impuls recent.")
            elif velocity > 10:
                notes.append(f"📐 **Ușoară accelerare** (+{velocity:.0f}% față de săptămâna anterioară): interesul crește gradual.")
            elif velocity < -30:
                notes.append(f"🧊 **Decelerare bruscă** ({velocity:.0f}% față de săptămâna anterioară): interesul s-a răcit rapid.")

        # Peak și context
        peak_val  = gt_df[keyword].max()
        peak_date = gt_df[keyword].idxmax()
        avg_val   = gt_df[keyword].mean()
        current   = gt_df[keyword].iloc[-1]

        notes.append(f"📌 **Peak de interes**: {peak_val:.0f}/100 înregistrat în **{peak_date.strftime('%B %Y')}**.")

        if current >= peak_val * 0.8:
            notes.append(f"🔝 **Context**: interesul curent ({current:.0f}) este aproape de nivelul maxim istoric — subiect extrem de relevant.")
        elif current >= avg_val:
            notes.append(f"📊 **Context**: interesul curent ({current:.0f}) este peste media perioadei ({avg_val:.0f}) — subiect activ.")
        else:
            notes.append(f"📉 **Context**: interesul curent ({current:.0f}) este sub media perioadei ({avg_val:.0f}) — subiect în declin.")

        # Spikes (vârfuri anormale)
        std_val = gt_df[keyword].std()
        spikes  = gt_df[keyword][gt_df[keyword] > avg_val + 2 * std_val]
        if len(spikes) > 0:
            spike_dates = ", ".join([d.strftime("%b %Y") for d in spikes.index[:3]])
            notes.append(f"🌋 **Vârfuri detectate** ({len(spikes)} evenimente): interes anormal de ridicat în {spike_dates}. Probabil corelat cu evenimente majore.")

    # ── GDELT ─────────────────────────────────────────────────────────────────
    if "tone" in gdelt and not gdelt["tone"].empty:
        t = gdelt["tone"]
        overall = t[t["series"].str.contains("Overall|Tone", case=False, na=False)]
        avg_tone = overall["value"].mean() if not overall.empty else t["value"].mean()

        if avg_tone < -2:
            notes.append(f"😟 **Ton mediatic puternic negativ** (scor: {avg_tone:.2f}): subiectul domină știrile negative.")
        elif avg_tone < -1:
            notes.append(f"😟 **Ton mediatic negativ** (scor: {avg_tone:.2f}): acoperire preponderent critică în presă.")
        elif avg_tone > 2:
            notes.append(f"😊 **Ton mediatic puternic pozitiv** (scor: {avg_tone:.2f}): subiectul este prezentat favorabil.")
        elif avg_tone > 1:
            notes.append(f"😊 **Ton mediatic pozitiv** (scor: {avg_tone:.2f}): acoperire mai degrabă pozitivă.")
        else:
            notes.append(f"😐 **Ton mediatic neutru** (scor: {avg_tone:.2f}): acoperire jurnalistică echilibrată.")

        # Tendință ton (s-a înrăutățit sau îmbunătățit?)
        if len(t) >= 14 and "series" in t.columns:
            ov = t[t["series"].str.contains("Overall|Tone", case=False, na=False)]
            if not ov.empty and len(ov) >= 10:
                recent_tone = ov["value"].iloc[-5:].mean()
                older_tone  = ov["value"].iloc[:5].mean()
                tone_delta  = recent_tone - older_tone
                if abs(tone_delta) > 0.5:
                    direction = "îmbunătățit" if tone_delta > 0 else "înrăutățit"
                    notes.append(f"📡 **Evoluție ton**: tonul mediatic s-a **{direction}** cu {abs(tone_delta):.2f} puncte față de începutul perioadei.")

    # GDELT buzz recent
    if "volume" in gdelt and not gdelt["volume"].empty:
        vol = gdelt["volume"]["volume"]
        if len(vol) >= 14:
            ratio = vol.iloc[-7:].mean() / max(vol.mean(), 0.001)
            if ratio > 1.5:
                notes.append(f"🔥 **Buzz media activ**: volumul de știri recent este de {ratio:.1f}× față de media perioadei.")
            elif ratio < 0.5:
                notes.append(f"🧊 **Media în retragere**: volumul recent e doar {ratio:.1f}× față de medie — subiectul pierde tracțiune mediatică.")

    # ── Wikipedia ─────────────────────────────────────────────────────────────
    if wiki_df is not None and not wiki_df.empty:
        total   = wiki_df["views"].sum()
        avg_day = wiki_df["views"].mean()
        peak_w  = wiki_df["views"].max()
        notes.append(f"📖 **Wikipedia**: {total:,.0f} vizualizări totale · medie {avg_day:,.0f}/zi · peak {peak_w:,.0f} vizualizări într-o zi.")

        # Trend Wikipedia
        n = len(wiki_df)
        if n >= 8:
            w_recent = wiki_df["views"].iloc[-n//4:].mean()
            w_old    = wiki_df["views"].iloc[:n//4].mean()
            w_pct    = ((w_recent - w_old) / max(w_old, 1)) * 100
            if w_pct > 20:
                notes.append(f"📖 Vizualizările Wikipedia sunt în creștere (+{w_pct:.0f}%) — interes crescut de documentare.")
            elif w_pct < -20:
                notes.append(f"📖 Vizualizările Wikipedia sunt în scădere ({w_pct:.0f}%) — interesul de documentare se reduce.")

    # ── Reddit ────────────────────────────────────────────────────────────────
    if reddit_df is not None and not reddit_df.empty:
        avg_ratio = reddit_df["upvote_ratio"].mean() * 100
        sentiment = "pozitiv" if avg_ratio > 65 else ("mixt" if avg_ratio > 45 else "negativ")
        notes.append(
            f"💬 **Reddit — sentiment {sentiment}**: {len(reddit_df)} posturi recente, "
            f"scor mediu {reddit_df['score'].mean():.0f}, aprobare {avg_ratio:.0f}%. "
            f"Subreddits active: {', '.join(reddit_df['subreddit'].value_counts().head(3).index.tolist())}."
        )

    # ── RSS ───────────────────────────────────────────────────────────────────
    if rss_articles:
        sources = list({a["source"] for a in rss_articles})
        notes.append(f"📡 **RSS**: {len(rss_articles)} articole recente din {len(sources)} surse ({', '.join(sources[:4])}).")

        # Frecvența pe zi
        from collections import Counter
        date_counts = Counter(a["date"] for a in rss_articles if a["date"] != "—")
        if date_counts:
            most_active = max(date_counts, key=date_counts.get)
            notes.append(f"📅 **Ziua cu cele mai multe știri**: {most_active} ({date_counts[most_active]} articole).")

    # ── Concluzie agregată ────────────────────────────────────────────────────
    if trend_score is not None:
        if trend_score >= 75:
            notes.append(f"🔥 **CONCLUZIE**: Subiect **extrem de activ** (scor {trend_score}/100) — prezent puternic în toate sursele monitorizate. Moment potrivit pentru acțiune sau comunicare.")
        elif trend_score >= 55:
            notes.append(f"📈 **CONCLUZIE**: Subiect **în trending** (scor {trend_score}/100) — interes ridicat și în creștere. Merită urmărit îndeaproape.")
        elif trend_score >= 35:
            notes.append(f"📊 **CONCLUZIE**: Subiect cu **interes moderat** (scor {trend_score}/100) — prezent în spațiul public, fără efervescență specială.")
        else:
            notes.append(f"🔇 **CONCLUZIE**: Subiect cu **interes scăzut** în prezent (scor {trend_score}/100) — sub radar mediatic și public.")

    return notes


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAȚĂ
# ═══════════════════════════════════════════════════════════════════════════════

st.title("📊 Trend Analyzer")
st.caption("Trenduri sociale · politice · economice — date publice, 100% gratuit")
st.divider()

with st.sidebar:
    st.header("⚙️ Configurare")

    kw1 = st.text_input("Subiect principal ★",
                         placeholder="ex: inflație, PSD, AI, energie…")
    kw2 = st.text_input("Compară cu (opțional)",
                         placeholder="ex: AUR, șomaj, gaze…")

    st.divider()

    region     = st.selectbox("Regiune", list(REGIONS.keys()))
    period     = st.selectbox("Perioadă", list(PERIODS.keys()), index=3)
    lang       = st.selectbox("Limbă știri",
                               ["Toate limbile", "Română", "Engleză"])
    chart_type = st.selectbox("Tip grafic", CHART_TYPES, index=0)

    st.divider()

    sources = st.multiselect(
        "Surse active",
        ["Google Trends","GDELT News","Wikipedia","World Bank","RSS News","Reddit"],
        default=["Google Trends","GDELT News","Wikipedia","RSS News"],
    )

    run_btn = st.button("🔍 Analizează", type="primary", use_container_width=True)

    st.divider()
    st.caption(
        "**Date publice gratuite:**\n"
        "Google Trends · GDELT · Wikipedia\n"
        "World Bank · RSS · Reddit\n\n"
        "*Rezultatele sunt memorate 1 oră.*"
    )

# ── Landing ───────────────────────────────────────────────────────────────────
if not run_btn:
    st.info("👈 Completează subiectul și apasă **Analizează**.")
    c1, c2 = st.columns(2)
    with c1:
        with st.expander("📊 Surse disponibile", expanded=True):
            st.markdown("""
| Sursă | Ce oferă |
|-------|----------|
| 🔍 Google Trends | Interes căutare + query-uri corelate |
| 📰 GDELT | Volum știri + ton mediatic |
| 📖 Wikipedia | Vizualizări pagină (RO+EN) |
| 🌍 World Bank | Indicatori economici oficiali |
| 📡 RSS | Articole din 9 surse românești + 6 internaționale |
| 💬 Reddit | Posturi + sentiment social |
            """)
    with c2:
        with st.expander("📈 Tipuri de grafice", expanded=True):
            st.markdown("""
| Tip | Descriere |
|-----|-----------|
| 📈 Linie | Evoluție clasică în timp |
| 📊 Bare | Comparație clară între perioade |
| 🔵 Arie | Linie cu suprafață colorată |
| 🗓️ Heatmap | Pattern-uri pe zile ale săptămânii |
| ⚖️ Normalizat | Toate sursele pe aceeași scară 0–100 |
            """)

elif not kw1.strip():
    st.warning("⚠️ Introdu cel puțin un subiect.")

else:
    keywords   = [k.strip() for k in [kw1, kw2] if k.strip()]
    gt_region, wb_country = REGIONS[region]
    timeframe, days, months = PERIODS[period]
    prefer_ro  = (region == "România (RO)")

    gt_df      = None
    gdelt      = {}
    wiki_df    = None
    wiki_title = None
    wb_data    = {}
    rss_arts   = []
    reddit_df  = None

    n_src        = len(sources)
    progress_bar = st.progress(0, text="Se inițializează…")
    score_slot   = st.empty()
    step         = 0

    # ── Google Trends ─────────────────────────────────────────────────────────
    if "Google Trends" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ Google Trends…")
        gt_df, related, err = fetch_google_trends(
            tuple(keywords), gt_region, timeframe
        )

        st.subheader("🔍 Google Trends — Interes de căutare")
        if err:
            st.warning(f"⚠️ {err}")
        elif gt_df is not None:
            series_dict = {col: gt_df[col] for col in gt_df.columns}
            fig = make_chart(series_dict, chart_type,
                             f"Interes relativ: {' vs '.join(keywords)}",
                             yaxis_title="Interes (0–100)")
            if "Heatmap" not in chart_type and "Normalizat" not in chart_type:
                fig.update_yaxes(range=[0, 105])
            st.plotly_chart(fig, use_container_width=True)

            if related:
                cols = st.columns(len(related))
                for i, (kw, df_rel) in enumerate(related.items()):
                    with cols[i]:
                        st.markdown(f"**Căutări corelate — *{kw}*:**")
                        for _, row in df_rel.iterrows():
                            st.markdown(f"- {row['query']} *(scor {row['value']})*")

    # ── GDELT ─────────────────────────────────────────────────────────────────
    if "GDELT News" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ GDELT News…")
        gdelt = fetch_gdelt(kw1.strip(), days)

        st.subheader("📰 GDELT News — Acoperire media")
        has_vol  = "volume" in gdelt and not gdelt["volume"].empty
        has_tone = "tone"   in gdelt and not gdelt["tone"].empty

        if has_vol:
            vol_series = {"Volum știri": gdelt["volume"]["volume"]}
            fig_vol = make_chart(vol_series, chart_type,
                                 "Volum știri/zi", yaxis_title="Articole/zi",
                                 height=320)
            st.plotly_chart(fig_vol, use_container_width=True)

        if has_tone:
            tone_df  = gdelt["tone"]
            tone_map = {"Positive":"#1cc88a","Negative":"#e74a3b",
                        "Overall Tone":"#f6c23e"}
            fig_tone = go.Figure()
            for sname in tone_df["series"].unique():
                sd = tone_df[tone_df["series"] == sname]
                fig_tone.add_trace(go.Scatter(
                    x=sd["date"], y=sd["value"], mode="lines", name=sname,
                    line=dict(color=tone_map.get(sname,"#858796"), width=2),
                ))
            fig_tone.add_hline(y=0, line_dash="dash",
                               line_color="rgba(0,0,0,0.25)")
            fig_tone.update_layout(
                title="Ton mediatic [pozitiv > 0  ·  negativ < 0]",
                height=300, hovermode="x unified", plot_bgcolor="#ffffff",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig_tone.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig_tone.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig_tone, use_container_width=True)

        if not has_vol and not has_tone:
            st.info("Date GDELT indisponibile. GDELT indexează predominant surse englezești — încearcă subiectul în engleză.")

        arts = gdelt.get("articles", [])
        if arts:
            with st.expander(f"📄 Articole GDELT ({len(arts)} găsite)"):
                for a in arts[:10]:
                    raw = a.get("seendate","")[:8]
                    ds  = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) >= 8 else "—"
                    st.markdown(f"- [{a.get('title','—')}]({a.get('url','#')})  \n"
                                f"  *{a.get('domain','—')}* · {ds}")

    # ── Wikipedia ─────────────────────────────────────────────────────────────
    if "Wikipedia" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ Wikipedia…")
        wiki_df, wiki_title = fetch_wikipedia_views(kw1.strip(), days, prefer_ro)

        st.subheader("📖 Wikipedia — Vizualizări pagină")
        if wiki_df is not None and not wiki_df.empty:
            st.caption(f"Articol: **{wiki_title}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("Total vizualizări", f"{wiki_df['views'].sum():,.0f}")
            c2.metric("Medie zilnică",     f"{wiki_df['views'].mean():,.0f}")
            c3.metric("Peak zilnic",       f"{wiki_df['views'].max():,.0f}")

            fig = make_chart({"Vizualizări": wiki_df["views"]},
                             chart_type,
                             f"Vizualizări Wikipedia: {wiki_title}",
                             yaxis_title="Vizualizări/zi", height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Nu s-a găsit o pagină Wikipedia pentru *{kw1}*.")

    # ── World Bank ─────────────────────────────────────────────────────────────
    if "World Bank" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ World Bank…")
        wb_data = fetch_world_bank(wb_country, months)

        st.subheader("🌍 World Bank — Indicatori economici")
        if wb_data:
            mc = st.columns(len(wb_data))
            for i, (label, df_wb) in enumerate(wb_data.items()):
                latest = df_wb.iloc[-1]["value"]
                prev   = df_wb.iloc[-2]["value"] if len(df_wb) > 1 else latest
                invert = "inverse" if any(w in label for w in ["Inflație","Șomaj"]) else "normal"
                mc[i].metric(label, f"{latest:.2f}%",
                             f"{latest-prev:+.2f}% vs an anterior",
                             delta_color=invert)

            wb_series = {lbl: df.set_index("year")["value"]
                         for lbl, df in wb_data.items()}
            fig = make_chart(wb_series, chart_type,
                             f"Indicatori economici — {region}",
                             yaxis_title="%", height=360)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Date World Bank indisponibile pentru această regiune.")

    # ── RSS ───────────────────────────────────────────────────────────────────
    if "RSS News" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ RSS News…")
        rss_arts = fetch_rss_news(kw1.strip(), lang, min(days, 30))

        st.subheader("📡 RSS News — Articole recente")
        if rss_arts:
            for art in rss_arts[:15]:
                c1, c2 = st.columns([5,1])
                c1.markdown(f"**[{art['title']}]({art['link']})**")
                c2.caption(f"{art['source']} · {art['date']}")
        else:
            st.info(f"Niciun articol găsit despre *{kw1}* în RSS-urile monitorizate.")

    # ── Reddit ─────────────────────────────────────────────────────────────────
    if "Reddit" in sources:
        step += 1
        progress_bar.progress(step / (n_src + 1), text="⏳ Reddit…")
        reddit_df, reddit_err = fetch_reddit(kw1.strip(), min(days, 30))

        st.subheader("💬 Reddit — Sentiment social")
        if reddit_df is not None and not reddit_df.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Posturi găsite",  len(reddit_df))
            c2.metric("Scor mediu",      f"{reddit_df['score'].mean():.0f}")
            c3.metric("Aprobare medie",  f"{reddit_df['upvote_ratio'].mean()*100:.0f}%")

            daily = reddit_df.groupby("date").size().reset_index(name="posts")
            daily_s = daily.set_index("date")["posts"]
            fig = make_chart({"Posturi/zi": daily_s}, chart_type,
                             "Activitate Reddit în timp",
                             yaxis_title="Posturi", height=280)
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 Posturi recente"):
                for _, row in reddit_df.head(8).iterrows():
                    st.markdown(f"- [{row['title']}]({row['url']})  \n"
                                f"  r/**{row['subreddit']}** · scor {row['score']}")
        else:
            st.info(f"Reddit: {reddit_err or 'date indisponibile'}.")

    # ── Grafic normalizat combinat ────────────────────────────────────────────
    combined = {}
    if gt_df is not None and kw1.strip() in gt_df.columns:
        combined["Google Trends"] = gt_df[kw1.strip()]
    if "volume" in gdelt and not gdelt["volume"].empty:
        combined["GDELT Volum"] = gdelt["volume"]["volume"]
    if wiki_df is not None and not wiki_df.empty:
        combined["Wikipedia"] = wiki_df["views"]

    if len(combined) >= 2:
        st.subheader("⚖️ Comparație normalizată — toate sursele")
        fig_norm = make_chart(combined, "⚖️ Normalizat (0–100)",
                              f"Toate sursele pe aceeași scară: {kw1}",
                              height=360)
        st.plotly_chart(fig_norm, use_container_width=True)

    # ── Trend Score & Concluzii ───────────────────────────────────────────────
    progress_bar.progress(1.0, text="✅ Finalizat!")
    trend_score, score_details = compute_trend_score(
        gt_df, gdelt, wiki_df, reddit_df, rss_arts, kw1.strip()
    )

    if trend_score is not None:
        cls   = "ts-high" if trend_score >= 70 else ("ts-mid" if trend_score >= 40 else "ts-low")
        emoji = "🔥" if trend_score >= 70 else ("📊" if trend_score >= 40 else "🔇")
        label = "Trending activ" if trend_score >= 70 else ("Interes moderat" if trend_score >= 40 else "Interes scăzut")
        score_slot.markdown(
            f'<div class="trend-score-box {cls}">{emoji} Trend Score: {trend_score}/100 — {label}</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.subheader("🧠 Interpretare & Concluzii")

    if trend_score is not None and score_details:
        with st.expander("📐 Detalii calcul Trend Score"):
            for d in score_details:
                st.markdown(f"- {d}")

    notes = build_interpretation(
        gt_df, gdelt, wiki_df, reddit_df, rss_arts, kw1.strip(), trend_score
    )
    for note in notes:
        st.markdown(f"> {note}")

    if not notes:
        st.info("Date insuficiente pentru interpretare automată.")

    st.success(
        f"Analiză: **{' vs '.join(keywords)}** · {region} · {period} · {lang}"
    )
