"""
Trend Analyzer v2
=================
Surse de date: Google Trends · GDELT News · Wikipedia · World Bank · RSS · Reddit
Deployment:    Streamlit Cloud (share.streamlit.io) — complet gratuit

Autor: generat cu Claude / Anthropic
"""

import time
import requests
import feedparser
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from urllib.parse import quote
import streamlit as st

try:
    from pytrends.request import TrendReq
    PYTRENDS_OK = True
except ImportError:
    PYTRENDS_OK = False

# ── Configurare pagină ────────────────────────────────────────────────────────
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
        font-size: 2.6rem; font-weight: 800; text-align: center;
        padding: 1.2rem 2rem; border-radius: 14px; margin-bottom: 1rem;
    }
    .ts-high { background: #d4edda; color: #155724; border: 2px solid #c3e6cb; }
    .ts-mid  { background: #fff3cd; color: #856404; border: 2px solid #ffeeba; }
    .ts-low  { background: #f8d7da; color: #721c24; border: 2px solid #f5c6cb; }
    blockquote { border-left: 4px solid #4e73df; padding-left: 1rem; color: #333; }
    .source-tag {
        display: inline-block; padding: 2px 8px; border-radius: 12px;
        font-size: 0.75rem; font-weight: 600; margin-right: 4px;
        background: #e9ecef; color: #495057;
    }
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

LANGUAGES = {
    "Toate limbile": "",
    "Română":        "sourcelang:rum",
    "Engleză":       "sourcelang:eng",
    "Germană":       "sourcelang:deu",
    "Franceză":      "sourcelang:fra",
}

RSS_FEEDS = {
    "Română": [
        ("Digi24",    "https://www.digi24.ro/rss"),
        ("HotNews",   "https://www.hotnews.ro/rss"),
        ("G4Media",   "https://www.g4media.ro/feed"),
        ("ProTV",     "https://stirileprotv.ro/rss.xml"),
        ("Mediafax",  "https://www.mediafax.ro/rss/"),
        ("Ziarul Fin","https://www.zf.ro/rss/"),
    ],
    "Engleză": [
        ("Reuters",     "https://feeds.reuters.com/reuters/topNews"),
        ("BBC",         "http://feeds.bbci.co.uk/news/rss.xml"),
        ("Al Jazeera",  "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian","https://www.theguardian.com/world/rss"),
        ("AP News",     "https://feeds.apnews.com/rss/topnews"),
    ],
    "Toate limbile": [
        ("Digi24",   "https://www.digi24.ro/rss"),
        ("HotNews",  "https://www.hotnews.ro/rss"),
        ("G4Media",  "https://www.g4media.ro/feed"),
        ("Reuters",  "https://feeds.reuters.com/reuters/topNews"),
        ("BBC",      "http://feeds.bbci.co.uk/news/rss.xml"),
        ("AP News",  "https://feeds.apnews.com/rss/topnews"),
    ],
}

WB_INDICATORS = {
    "FP.CPI.TOTL.ZG":  "Inflație (%/an)",
    "NY.GDP.MKTP.KD.ZG":"Creștere PIB (%/an)",
    "SL.UEM.TOTL.ZS":  "Șomaj (%)",
}

COLORS = ["#4e73df", "#e74a3b", "#1cc88a", "#f6c23e", "#9b59b6", "#e67e22"]
HEADERS = {"User-Agent": "TrendAnalyzer/2.0 (research tool)"}

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
WB_BASE    = "https://api.worldbank.org/v2"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
WIKI_VIEWS  = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCȚII DE DATE
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_google_trends(keywords: list, region_code: str, timeframe: str):
    """Interes de căutare Google + queries corelate."""
    if not PYTRENDS_OK:
        return None, None, "pytrends nu este instalat."
    try:
        pt = TrendReq(hl="ro-RO", tz=120, timeout=(10, 30))
        pt.build_payload(keywords[:5], cat=0, timeframe=timeframe,
                         geo=region_code, gprop="")
        df = pt.interest_over_time()
        if df.empty:
            return None, None, "Fără date pentru această combinație."
        df = df.drop(columns=["isPartial"], errors="ignore")
        time.sleep(0.8)

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
        return None, None, str(exc)


def fetch_gdelt(keyword: str, days: int, lang_filter: str = ""):
    """Volum știri și ton mediatic din GDELT."""
    # Încearcă mai întâi fără filtru de limbă, dacă nu vin date adaugă filtrul
    def _query(q):
        end_dt   = datetime.utcnow()
        start_dt = end_dt - timedelta(days=days)
        sdt = start_dt.strftime("%Y%m%d%H%M%S")
        edt = end_dt.strftime("%Y%m%d%H%M%S")
        result = {}

        for mode, key in [("timelinevol", "volume"), ("timelineTone", "tone"), ("artlist", "articles")]:
            try:
                params = {"query": q, "mode": mode, "format": "json",
                          "startdatetime": sdt, "enddatetime": edt, "smoothing": 3}
                if mode == "artlist":
                    params.update({"maxrecords": 10, "sort": "datedesc"})
                    del params["smoothing"]

                r = requests.get(GDELT_BASE, params=params,
                                 headers=HEADERS, timeout=20)
                if r.status_code != 200 or not r.text.strip():
                    continue
                js = r.json()

                if mode == "artlist":
                    result["articles"] = js.get("articles", [])
                    continue

                rows = []
                for series in js.get("timeline", []):
                    label = series.get("series", key)
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
                result[f"{key}_error"] = str(exc)
        return result

    res = _query(keyword)
    # Dacă nu avem volume, încearcă fără filtru de limbă
    if "volume" not in res and lang_filter:
        res = _query(keyword)
    return res


def fetch_wikipedia_views(keyword: str, days: int):
    """Caută articolul Wikipedia și returnează page views zilnice."""
    try:
        # Căutare articol
        sr = requests.get(WIKI_SEARCH, params={
            "action": "query", "list": "search",
            "srsearch": keyword, "format": "json", "srlimit": 1,
        }, headers=HEADERS, timeout=10)
        if sr.status_code != 200:
            return None, None

        hits = sr.json().get("query", {}).get("search", [])
        if not hits:
            return None, None

        title = hits[0]["title"].replace(" ", "_")
        end_dt   = datetime.utcnow()
        start_dt = end_dt - timedelta(days=days)

        vr = requests.get(
            f"{WIKI_VIEWS}/en.wikipedia/all-access/all-agents"
            f"/{quote(title)}/daily"
            f"/{start_dt.strftime('%Y%m%d')}/{end_dt.strftime('%Y%m%d')}",
            headers=HEADERS, timeout=10,
        )
        if vr.status_code != 200:
            return None, title

        items = vr.json().get("items", [])
        if not items:
            return None, title

        rows = [{"date": pd.to_datetime(it["timestamp"][:8], format="%Y%m%d"),
                 "views": it["views"]} for it in items]
        return pd.DataFrame(rows).set_index("date"), title

    except Exception:
        return None, None


def fetch_world_bank(wb_country: str, months: int):
    """Indicatori economici oficiali de la World Bank."""
    end_year   = datetime.now().year
    start_year = max(end_year - max(months // 12, 3), end_year - 12)
    date_range = f"{start_year}:{end_year}"

    results = {}
    for indicator, label in WB_INDICATORS.items():
        try:
            r = requests.get(
                f"{WB_BASE}/country/{wb_country}/indicator/{indicator}",
                params={"format": "json", "date": date_range, "per_page": "20"},
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


def fetch_rss_news(keyword: str, lang_key: str, days: int = 30):
    """Filtrează articole RSS care menționează keyword-ul."""
    feeds = RSS_FEEDS.get(lang_key, RSS_FEEDS["Toate limbile"])
    kw_lower = keyword.lower()
    cutoff   = datetime.now() - timedelta(days=min(days, 30))
    articles = []

    for source_name, feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                if kw_lower not in (title + " " + summary).lower():
                    continue
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6])
                    if pub_dt < cutoff:
                        continue
                    date_str = pub_dt.strftime("%Y-%m-%d")
                else:
                    date_str = "—"
                articles.append({
                    "title":  title,
                    "link":   entry.get("link", "#"),
                    "source": source_name,
                    "date":   date_str,
                })
        except Exception:
            pass

    articles.sort(key=lambda x: x["date"], reverse=True)
    return articles[:20]


def fetch_reddit(keyword: str, days: int = 30):
    """Posturi Reddit recente + sentiment bazat pe upvote ratio."""
    try:
        r = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": keyword, "sort": "new", "t": "month", "limit": 100},
            headers={"User-Agent": "TrendAnalyzer:v2.0 (by /u/trendapp)"},
            timeout=15,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"

        posts = r.json().get("data", {}).get("children", [])
        if not posts:
            return None, "Fără posturi găsite."

        cutoff = datetime.now() - timedelta(days=days)
        rows = []
        for post in posts:
            d = post.get("data", {})
            created = datetime.fromtimestamp(d.get("created_utc", 0))
            if created < cutoff:
                continue
            rows.append({
                "date":         created.date(),
                "title":        d.get("title", ""),
                "score":        d.get("score", 0),
                "comments":     d.get("num_comments", 0),
                "subreddit":    d.get("subreddit", ""),
                "url":          f"https://reddit.com{d.get('permalink', '')}",
                "upvote_ratio": d.get("upvote_ratio", 0.5),
            })

        if not rows:
            return None, "Nicio postare recentă."
        return pd.DataFrame(rows), None

    except Exception as exc:
        return None, str(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# TREND SCORE & INTERPRETARE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trend_score(gt_df, gdelt, wiki_df, reddit_df, rss_articles, keyword):
    """Calculează un scor compozit 0–100 din toate sursele disponibile."""
    scores  = []
    details = []

    # Google Trends
    if gt_df is not None and keyword in gt_df.columns:
        vals = gt_df[keyword].values
        n = len(vals)
        if n >= 4:
            recent = vals[-n // 4:].mean()
            old    = vals[:n // 4].mean()
            s = min(100, max(0, 50 + (recent - old) / max(old, 1) * 30))
        else:
            s = float(vals.mean())
        scores.append(s)
        details.append(f"Google Trends: **{s:.0f}/100**")

    # GDELT volume
    if "volume" in gdelt and not gdelt["volume"].empty:
        vol = gdelt["volume"]["volume"]
        if len(vol) >= 7:
            s = min(100, (vol.iloc[-7:].mean() / max(vol.mean(), 0.001)) * 50)
        else:
            s = 50.0
        scores.append(s)
        details.append(f"GDELT media: **{s:.0f}/100**")

    # Wikipedia
    if wiki_df is not None and not wiki_df.empty:
        views = wiki_df["views"].values
        n = len(views)
        if n >= 4:
            recent = views[-n // 4:].mean()
            old    = views[:n // 4].mean()
            s = min(100, max(0, 50 + (recent - old) / max(old, 1) * 30))
        else:
            s = 50.0
        scores.append(s)
        details.append(f"Wikipedia views: **{s:.0f}/100**")

    # Reddit
    if reddit_df is not None and not reddit_df.empty:
        s = float(reddit_df["upvote_ratio"].mean() * 100)
        scores.append(s)
        details.append(f"Reddit aprobare: **{s:.0f}/100**")

    # RSS
    if rss_articles:
        s = min(100, len(rss_articles) * 8)
        scores.append(s)
        details.append(f"RSS articole ({len(rss_articles)}): **{s:.0f}/100**")

    if not scores:
        return None, []

    composite = round(sum(scores) / len(scores))
    return composite, details


def build_interpretation(gt_df, gdelt, wiki_df, reddit_df, rss_articles,
                          keyword, trend_score):
    notes = []

    # Google Trends
    if gt_df is not None and keyword in gt_df.columns:
        vals = gt_df[keyword].values
        n    = len(vals)
        if n >= 4:
            pct = ((vals[-n // 4:].mean() - vals[:n // 4].mean())
                   / max(vals[:n // 4].mean(), 1)) * 100
            if pct > 25:
                notes.append(f"📈 **Interes în creștere** (+{pct:.0f}%): căutările pentru *{keyword}* au crescut semnificativ.")
            elif pct < -25:
                notes.append(f"📉 **Interes în scădere** ({pct:.0f}%): căutările pentru *{keyword}* s-au redus.")
            else:
                notes.append(f"➡️ **Interes stabil** (variație {pct:+.0f}%): căutările rămân relativ constante.")
        peak = gt_df[keyword].idxmax()
        notes.append(f"📌 **Peak de interes**: cel mai ridicat nivel a fost în **{peak.strftime('%B %Y')}**.")

    # GDELT ton
    if "tone" in gdelt and not gdelt["tone"].empty:
        t = gdelt["tone"]
        overall = t[t["series"].str.contains("Overall|Tone", case=False, na=False)]
        avg = overall["value"].mean() if not overall.empty else t["value"].mean()
        if avg < -1.5:
            notes.append(f"😟 **Ton mediatic negativ** (scor: {avg:.2f}): subiectul este tratat preponderent negativ în presă.")
        elif avg > 1.5:
            notes.append(f"😊 **Ton mediatic pozitiv** (scor: {avg:.2f}): subiectul are o acoperire mai degrabă pozitivă.")
        else:
            notes.append(f"😐 **Ton mediatic neutru** (scor: {avg:.2f}): acoperire jurnalistică echilibrată.")

    # GDELT buzz recent
    if "volume" in gdelt and not gdelt["volume"].empty:
        vol = gdelt["volume"]["volume"]
        if len(vol) >= 14:
            if vol.iloc[-7:].mean() > vol.mean() * 1.4:
                notes.append("🔥 **Subiect în trend activ**: volumul media din ultimele 7 zile depășește semnificativ media perioadei.")

    # Wikipedia
    if wiki_df is not None and not wiki_df.empty:
        total   = wiki_df["views"].sum()
        avg_day = wiki_df["views"].mean()
        notes.append(f"📖 **Wikipedia**: {total:,.0f} vizualizări totale, medie de {avg_day:,.0f}/zi.")

    # Reddit
    if reddit_df is not None and not reddit_df.empty:
        notes.append(
            f"💬 **Reddit**: {len(reddit_df)} posturi recente, "
            f"scor mediu {reddit_df['score'].mean():.0f}, "
            f"aprobare {reddit_df['upvote_ratio'].mean()*100:.0f}%."
        )

    # RSS
    if rss_articles:
        sources = list({a["source"] for a in rss_articles})[:4]
        notes.append(f"📡 **RSS**: {len(rss_articles)} articole recente găsite în {', '.join(sources)}.")

    # Concluzie finală
    if trend_score is not None:
        if trend_score >= 70:
            notes.append(f"🔥 **Concluzie**: Subiectul este **activ și în trending** (scor {trend_score}/100) — acoperire largă, interes ridicat.")
        elif trend_score >= 40:
            notes.append(f"📊 **Concluzie**: Subiectul are **interes moderat** (scor {trend_score}/100) — prezent în spațiul public fără efervescență specială.")
        else:
            notes.append(f"🔇 **Concluzie**: Subiectul are **interes scăzut** în prezent (scor {trend_score}/100).")

    return notes


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAȚĂ UTILIZATOR
# ═══════════════════════════════════════════════════════════════════════════════

st.title("📊 Trend Analyzer")
st.caption("Trenduri sociale · politice · economice — date publice, 100% gratuit")
st.divider()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configurare")

    kw1 = st.text_input("Subiect principal ★",
                        placeholder="ex: inflație, PSD, AI, energie…")
    kw2 = st.text_input("Compară cu (opțional)",
                        placeholder="ex: PNL, șomaj, gaze…")

    st.divider()

    region = st.selectbox("Regiune", list(REGIONS.keys()))
    period = st.selectbox("Perioadă", list(PERIODS.keys()), index=3)
    lang   = st.selectbox("Limbă știri", list(LANGUAGES.keys()))

    st.divider()

    sources = st.multiselect(
        "Surse active",
        ["Google Trends", "GDELT News", "Wikipedia",
         "World Bank", "RSS News", "Reddit"],
        default=["Google Trends", "GDELT News", "Wikipedia", "RSS News"],
    )

    run_btn = st.button("🔍 Analizează", type="primary", use_container_width=True)

    st.divider()
    st.caption(
        "**Surse de date:**\n"
        "- [Google Trends](https://trends.google.com)\n"
        "- [GDELT Project](https://www.gdeltproject.org)\n"
        "- [Wikipedia](https://wikipedia.org)\n"
        "- [World Bank](https://data.worldbank.org)\n"
        "- RSS: Digi24, HotNews, G4Media, Reuters, BBC\n"
        "- [Reddit](https://reddit.com)\n\n"
        "*Toate datele sunt publice și gratuite.*"
    )

# ── Landing ───────────────────────────────────────────────────────────────────
if not run_btn:
    st.info("👈 Completează subiectul în panoul din stânga și apasă **Analizează**.")
    with st.expander("ℹ️ Surse disponibile și ce oferă fiecare", expanded=True):
        st.markdown("""
| Sursă | Ce oferă | Necesită cont? |
|-------|----------|---------------|
| 🔍 **Google Trends** | Evoluția interesului de căutare în timp, query-uri corelate | Nu |
| 📰 **GDELT News** | Volum știri + ton mediatic (pozitiv/negativ) | Nu |
| 📖 **Wikipedia** | Vizualizări zilnice ale paginii articolului | Nu |
| 🌍 **World Bank** | Inflație, PIB, șomaj — date oficiale pe țară | Nu |
| 📡 **RSS News** | Articole filtrate din Digi24, HotNews, Reuters, BBC | Nu |
| 💬 **Reddit** | Posturi recente + sentiment social (upvote ratio) | Nu |

**Trend Score** = medie ponderată a tuturor surselor active → un singur număr 0–100.
        """)
    with st.expander("💡 Sfaturi pentru rezultate mai bune"):
        st.markdown("""
- **Subiecte politice**: încearcă numele partidului sau al politicianului
- **Subiecte economice**: *inflație*, *curs valutar*, *șomaj*, *energie*
- **Comparație**: adaugă un al doilea subiect pentru perspectivă relativă
- **Română + global**: lasă "Toate limbile" pentru GDELT; RSS Română pentru știri locale
- **Perioadă lungă**: "Ultimii 2 ani" sau "5 ani" dezvăluie trenduri structurale
        """)

elif not kw1.strip():
    st.warning("⚠️ Introdu cel puțin un subiect în câmpul **Subiect principal**.")

else:
    # ── Inițializare variabile ─────────────────────────────────────────────────
    keywords   = [k.strip() for k in [kw1, kw2] if k.strip()]
    gt_region, wb_country = REGIONS[region]
    timeframe, days, months = PERIODS[period]
    lang_filter = LANGUAGES[lang]
    rss_lang    = lang if lang in RSS_FEEDS else "Toate limbile"

    gt_df       = None
    gdelt       = {}
    wiki_df     = None
    wiki_title  = None
    wb_data     = {}
    rss_arts    = []
    reddit_df   = None

    n_sources    = len(sources)
    step         = 0
    progress_bar = st.progress(0, text="Se inițializează…")
    score_slot   = st.empty()   # rezervă loc pentru Trend Score (apare la final)

    # ══════════════════════════════════════════════════════════════════════════
    # GOOGLE TRENDS
    # ══════════════════════════════════════════════════════════════════════════
    if "Google Trends" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ Google Trends…")
        gt_df, related, err = fetch_google_trends(keywords, gt_region, timeframe)

        st.subheader("🔍 Google Trends — Interes de căutare")
        if err:
            st.warning(f"Google Trends: {err}")
        elif gt_df is not None:
            fig = go.Figure()
            for i, col in enumerate(gt_df.columns):
                fig.add_trace(go.Scatter(
                    x=gt_df.index, y=gt_df[col],
                    mode="lines", name=col,
                    line=dict(width=2.5, color=COLORS[i % len(COLORS)]),
                    hovertemplate=f"<b>{col}</b>: %{{y}}<extra></extra>",
                ))
            fig.update_layout(
                title=f"Interes relativ: {' vs '.join(keywords)}",
                yaxis_title="Interes (0–100)", hovermode="x unified",
                height=370, plot_bgcolor="#ffffff",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", range=[0, 105])
            st.plotly_chart(fig, use_container_width=True)

            if related:
                cols = st.columns(len(related))
                for i, (kw, df_rel) in enumerate(related.items()):
                    with cols[i]:
                        st.markdown(f"**Căutări corelate — *{kw}*:**")
                        for _, row in df_rel.iterrows():
                            st.markdown(f"- {row['query']} *(scor {row['value']})*")

    # ══════════════════════════════════════════════════════════════════════════
    # GDELT
    # ══════════════════════════════════════════════════════════════════════════
    if "GDELT News" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ GDELT News…")
        gdelt = fetch_gdelt(kw1.strip(), days, lang_filter)

        st.subheader("📰 GDELT News — Acoperire media")
        has_vol  = "volume" in gdelt and not gdelt["volume"].empty
        has_tone = "tone"   in gdelt and not gdelt["tone"].empty

        if has_vol and has_tone:
            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=("Volum știri/zi (smoothed)",
                                "Ton mediatic  [pozitiv > 0  ·  negativ < 0]"),
                shared_xaxes=True, vertical_spacing=0.13,
                row_heights=[0.55, 0.45],
            )
            vd = gdelt["volume"]
            fig.add_trace(go.Scatter(
                x=vd.index, y=vd["volume"], mode="lines", fill="tozeroy",
                name="Volum", line=dict(color="#4e73df", width=2),
                fillcolor="rgba(78,115,223,0.15)",
            ), row=1, col=1)

            tone_colors = {"Positive": "#1cc88a", "Negative": "#e74a3b",
                           "Overall Tone": "#f6c23e"}
            for sname in gdelt["tone"]["series"].unique():
                sd = gdelt["tone"][gdelt["tone"]["series"] == sname]
                fig.add_trace(go.Scatter(
                    x=sd["date"], y=sd["value"], mode="lines", name=sname,
                    line=dict(color=tone_colors.get(sname, "#858796"), width=2),
                ), row=2, col=1)
            fig.add_hline(y=0, line_dash="dash",
                          line_color="rgba(0,0,0,0.25)", row=2, col=1)
            fig.update_layout(height=560, hovermode="x unified",
                              plot_bgcolor="#ffffff",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02))
            fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig, use_container_width=True)

        elif has_vol:
            vd = gdelt["volume"]
            fig = go.Figure(go.Scatter(
                x=vd.index, y=vd["volume"], mode="lines", fill="tozeroy",
                line=dict(color="#4e73df"),
            ))
            fig.update_layout(title="Volum știri în timp", height=300,
                              plot_bgcolor="#ffffff")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Date GDELT indisponibile pentru această interogare. Încearcă un termen mai scurt în engleză.")

        arts = gdelt.get("articles", [])
        if arts:
            with st.expander(f"📄 Articole GDELT recente ({len(arts)} găsite)"):
                for a in arts[:8]:
                    raw_dt  = a.get("seendate", "")[:8]
                    date_s  = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}" if len(raw_dt) >= 8 else "—"
                    st.markdown(f"- [{a.get('title','—')}]({a.get('url','#')})  \n"
                                f"  *{a.get('domain','—')}* · {date_s}")

    # ══════════════════════════════════════════════════════════════════════════
    # WIKIPEDIA
    # ══════════════════════════════════════════════════════════════════════════
    if "Wikipedia" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ Wikipedia…")
        wiki_df, wiki_title = fetch_wikipedia_views(kw1.strip(), days)

        st.subheader("📖 Wikipedia — Vizualizări pagină")
        if wiki_df is not None and not wiki_df.empty:
            clean_title = wiki_title.replace("_", " ")
            st.caption(f"Articol identificat: **{clean_title}**")

            col1, col2, col3 = st.columns(3)
            col1.metric("Total vizualizări",   f"{wiki_df['views'].sum():,.0f}")
            col2.metric("Medie zilnică",       f"{wiki_df['views'].mean():,.0f}")
            col3.metric("Peak zilnic",         f"{wiki_df['views'].max():,.0f}")

            fig = go.Figure(go.Scatter(
                x=wiki_df.index, y=wiki_df["views"],
                mode="lines", fill="tozeroy", name="Vizualizări",
                line=dict(color="#1cc88a", width=2),
                fillcolor="rgba(28,200,138,0.15)",
            ))
            fig.update_layout(
                title=f"Vizualizări Wikipedia: {clean_title}",
                yaxis_title="Vizualizări/zi", height=320,
                hovermode="x unified", plot_bgcolor="#ffffff",
            )
            fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"Nu s-a găsit o pagină Wikipedia clară pentru *{kw1}*.")

    # ══════════════════════════════════════════════════════════════════════════
    # WORLD BANK
    # ══════════════════════════════════════════════════════════════════════════
    if "World Bank" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ World Bank…")
        wb_data = fetch_world_bank(wb_country, months)

        st.subheader("🌍 World Bank — Indicatori economici")
        if wb_data:
            metric_cols = st.columns(len(wb_data))
            for i, (label, df_wb) in enumerate(wb_data.items()):
                latest = df_wb.iloc[-1]["value"]
                prev   = df_wb.iloc[-2]["value"] if len(df_wb) > 1 else latest
                delta  = latest - prev
                invert = "inverse" if any(w in label for w in ["Inflație", "Șomaj"]) else "normal"
                metric_cols[i].metric(
                    label=f"{label}",
                    value=f"{latest:.2f}%",
                    delta=f"{delta:+.2f}% vs an anterior",
                    delta_color=invert,
                )

            fig = go.Figure()
            for i, (label, df_wb) in enumerate(wb_data.items()):
                fig.add_trace(go.Scatter(
                    x=df_wb["year"], y=df_wb["value"],
                    mode="lines+markers", name=label,
                    line=dict(color=COLORS[i % len(COLORS)], width=2),
                    marker=dict(size=5),
                ))
            fig.update_layout(
                title=f"Indicatori economici — {region}",
                yaxis_title="%", hovermode="x unified", height=360,
                plot_bgcolor="#ffffff",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0")
            fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Date World Bank indisponibile pentru această regiune.")

    # ══════════════════════════════════════════════════════════════════════════
    # RSS NEWS
    # ══════════════════════════════════════════════════════════════════════════
    if "RSS News" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ RSS News…")
        rss_arts = fetch_rss_news(kw1.strip(), rss_lang, min(days, 30))

        st.subheader("📡 RSS News — Articole recente")
        if rss_arts:
            for art in rss_arts[:12]:
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**[{art['title']}]({art['link']})**")
                c2.caption(f"{art['source']} · {art['date']}")
        else:
            st.info(f"Niciun articol găsit despre *{kw1}* în sursele RSS monitorizate.")

    # ══════════════════════════════════════════════════════════════════════════
    # REDDIT
    # ══════════════════════════════════════════════════════════════════════════
    if "Reddit" in sources:
        step += 1
        progress_bar.progress(step / (n_sources + 1), text="⏳ Reddit…")
        reddit_df, reddit_err = fetch_reddit(kw1.strip(), min(days, 30))

        st.subheader("💬 Reddit — Sentiment social")
        if reddit_df is not None and not reddit_df.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Posturi găsite",  len(reddit_df))
            c2.metric("Scor mediu",      f"{reddit_df['score'].mean():.0f}")
            c3.metric("Aprobare medie",  f"{reddit_df['upvote_ratio'].mean()*100:.0f}%")

            daily = reddit_df.groupby("date").size().reset_index(name="posts")
            fig = go.Figure(go.Bar(
                x=daily["date"], y=daily["posts"],
                marker_color="#ff4500",
            ))
            fig.update_layout(title="Activitate Reddit în timp",
                              height=280, plot_bgcolor="#ffffff",
                              yaxis_title="Posturi/zi")
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 Posturi recente"):
                for _, row in reddit_df.head(8).iterrows():
                    st.markdown(
                        f"- [{row['title']}]({row['url']})  \n"
                        f"  r/**{row['subreddit']}** · scor {row['score']} · "
                        f"{row['comments']} comentarii"
                    )
        else:
            st.info(f"Reddit: {reddit_err or 'date indisponibile'}.")

    # ══════════════════════════════════════════════════════════════════════════
    # TREND SCORE & CONCLUZII
    # ══════════════════════════════════════════════════════════════════════════
    progress_bar.progress(1.0, text="✅ Finalizat!")

    trend_score, score_details = compute_trend_score(
        gt_df, gdelt, wiki_df, reddit_df, rss_arts, kw1.strip()
    )

    if trend_score is not None:
        cls   = "ts-high" if trend_score >= 70 else ("ts-mid" if trend_score >= 40 else "ts-low")
        emoji = "🔥" if trend_score >= 70 else ("📊" if trend_score >= 40 else "🔇")
        label = "Trending activ" if trend_score >= 70 else ("Interes moderat" if trend_score >= 40 else "Interes scăzut")
        score_slot.markdown(
            f'<div class="trend-score-box {cls}">'
            f'{emoji} Trend Score: {trend_score}/100 — {label}'
            f'</div>',
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
        f"Analiză completă: **{' vs '.join(keywords)}** · "
        f"{region} · {period} · {lang}"
    )
