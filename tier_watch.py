#!/usr/bin/env python3
"""Suivi quotidien des tiers Sorare Set (Reserve / Roster / Key / Star / Icon).

Suit tous les joueurs des championnats listés dans config.json, repère ceux que tu possèdes
(cartes Set de ta galerie publique) et produit :
  - report.md          : rapport du jour (corps de l'issue GitHub)
  - data/tiers.json    : état courant de chaque joueur
  - data/history.csv   : historique de tous les changements
  - docs/index.html    : tableau de bord consultable (filtres, mes joueurs, changements récents)

Usage : python tier_watch.py            (stdlib uniquement, Python 3.9+)
Variable optionnelle : SORARE_API_KEY  (clé gratuite sur sorare.com/settings/developer)
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.sorare.com/graphql"
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "data", "tiers.json")
HISTORY_PATH = os.path.join(ROOT, "data", "history.csv")
REPORT_PATH = os.path.join(ROOT, "report.md")
DASHBOARD_PATH = os.path.join(ROOT, "docs", "index.html")

# Valeurs de l'enum GraphQL `GameplayTier` -> nom affiché dans Sorare Set
TIERS = {
    "DNP": ("Reserve", 1.0), "DNP_PLUS": ("Reserve+", 1.5),
    "ROSTER": ("Roster", 2.0), "ROSTER_PLUS": ("Roster+", 2.5),
    "IMPACT": ("Key", 3.0), "IMPACT_PLUS": ("Key+", 3.5),
    "STAR": ("Star", 4.0), "STAR_PLUS": ("Star+", 4.5),
    "GOAT": ("Icon", 5.0),
}
HISTORY_HEADER = ["date", "slug", "joueur", "club", "championnat", "ancien_tier", "nouveau_tier", "possede"]
MAX_ROWS_IN_REPORT = 150  # une issue GitHub est limitée à ~65 000 caractères


def label(t):
    return TIERS[t][0] if t in TIERS else "Sans tier"


def rank(t):
    return TIERS[t][1] if t in TIERS else 0.0


# --------------------------------------------------------------------------- API

def gql(query, variables=None, retries=6):
    headers = {"content-type": "application/json", "user-agent": "sorare-tier-watch"}
    if os.environ.get("SORARE_API_KEY"):
        headers["APIKEY"] = os.environ["SORARE_API_KEY"]
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for _ in range(retries):
        req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After") or 30)
                print(f"HTTP {e.code}, pause {wait}s", file=sys.stderr)
                time.sleep(wait + 1)
                continue
            raise SystemExit(f"Erreur HTTP {e.code}: {e.read()[:500]!r}")
        if payload.get("errors"):
            raise SystemExit("Erreur GraphQL : " + json.dumps(payload["errors"], ensure_ascii=False)[:1500])
        time.sleep(0.4 if os.environ.get("SORARE_API_KEY") else 3.1)  # 200/min avec clé, 20/min sans
        return payload["data"]
    raise SystemExit("Trop d'erreurs successives, abandon.")


Q_TEAMS = """query($s: String!) { football { competition(slug: $s) {
  displayName teams(first: 40) { nodes { ... on Club { slug name } } } } } }"""

Q_PLAYERS = """query($s: String!, $a: String) { football { club(slug: $s) {
  activePlayers(first: 50, after: $a) {
    nodes { slug displayName position gameplayTier }
    pageInfo { hasNextPage endCursor } } } } }"""

Q_MY_CARDS = """query($u: String!, $a: String) { user(slug: $u) {
  cards(sport: FOOTBALL, rarities: [common], first: 50, after: $a) {
    nodes { ... on Card { cardSet { slug startDate } player { slug } } }
    pageInfo { hasNextPage endCursor } } } }"""


def fetch_all_players(competitions):
    players = {}
    for comp in competitions:
        c = gql(Q_TEAMS, {"s": comp})["football"]["competition"]
        league = c["displayName"]
        clubs = [n for n in c["teams"]["nodes"] if n]
        print(f"{league} : {len(clubs)} clubs", file=sys.stderr)
        for club in clubs:
            after = None
            while True:
                ap = gql(Q_PLAYERS, {"s": club["slug"], "a": after})["football"]["club"]["activePlayers"]
                for p in ap["nodes"]:
                    if p["position"] == "Coach":
                        continue
                    players[p["slug"]] = {
                        "name": p["displayName"], "club": club["name"], "league": league,
                        "pos": p["position"], "tier": p["gameplayTier"],
                    }
                if not ap["pageInfo"]["hasNextPage"]:
                    break
                after = ap["pageInfo"]["endCursor"]
    return players


def fetch_my_players(user_slug, set_slug):
    """Joueurs dont tu possèdes au moins une carte Set (galerie publique, pas besoin de connexion).

    set_slug : None = tous les Sets ; "auto" = le Set le plus récent de ta galerie ; sinon un slug précis.
    Retourne (dict joueur -> nb de cartes, nom du Set retenu).
    """
    cards, starts, after = [], {}, None
    while True:
        conn = gql(Q_MY_CARDS, {"u": user_slug, "a": after})["user"]["cards"]
        for card in conn["nodes"]:
            if card and card.get("cardSet") and card.get("player"):
                cs = card["cardSet"]
                starts[cs["slug"]] = cs.get("startDate") or ""
                cards.append((cs["slug"], card["player"]["slug"]))
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    if set_slug == "auto":
        set_slug = max(starts, key=starts.get) if starts else None
    owned = {}
    for cs, player in cards:
        if set_slug is None or cs == set_slug:
            owned[player] = owned.get(player, 0) + 1
    print(f"Galerie : {len(cards)} cartes Set ({', '.join(sorted(starts))}) -> "
          f"Set retenu : {set_slug or 'tous'}, {len(owned)} joueurs", file=sys.stderr)
    return owned, set_slug


# ------------------------------------------------------------------------ report

def link(slug, p):
    return f"[{p['name']}](https://sorare.com/football/players/{slug})"


def change_table(rows, owned):
    rows = sorted(rows, key=lambda r: (-rank(r[2]["tier"]), r[2]["league"], r[2]["name"]))
    out = ["| Joueur | Club | Championnat | Avant | Après |", "|---|---|---|---|---|"]
    for slug, old, p in rows[:MAX_ROWS_IN_REPORT]:
        mark = " ✅" if slug in owned else ""
        out.append(f"| {link(slug, p)}{mark} | {p['club']} | {p['league']} | {label(old)} | **{label(p['tier'])}** |")
    if len(rows) > MAX_ROWS_IN_REPORT:
        out.append(f"\n… et {len(rows) - MAX_ROWS_IN_REPORT} autres (voir `data/history.csv` ou le tableau de bord).")
    return out + [""]


def build_report(today, current, previous, owned, first_run, ups, downs):
    L = [f"# Tiers Sorare Set — {today}", ""]
    if first_run:
        L += [f"Première exécution : état de référence enregistré pour **{len(current)} joueurs**. "
              "Les changements seront signalés à partir de demain.", ""]
        leagues = sorted({p["league"] for p in current.values()})
        tiers = sorted({p["tier"] for p in current.values()}, key=lambda t: -rank(t))
        L += ["| Championnat | " + " | ".join(label(t) for t in tiers) + " |",
              "|---|" + "---|" * len(tiers)]
        for lg in leagues:
            cnt = [sum(1 for p in current.values() if p["league"] == lg and p["tier"] == t) for t in tiers]
            L.append(f"| {lg} | " + " | ".join(map(str, cnt)) + " |")
        L.append("")
        if owned:
            mine = sorted((s for s in owned if s in current), key=lambda s: (-rank(current[s]["tier"]), current[s]["name"]))
            L += [f"## Mes joueurs ({len(mine)})", "", "| Joueur | Club | Tier |", "|---|---|---|"]
            L += [f"| {link(s, current[s])} | {current[s]['club']} | {label(current[s]['tier'])} |" for s in mine]
            outside = [s for s in owned if s not in current]
            if outside:
                L += ["", f"{len(outside)} joueur(s) de ta galerie hors des championnats suivis."]
        return "\n".join(L) + "\n"

    my_ups = [r for r in ups if r[0] in owned]
    my_downs = [r for r in downs if r[0] in owned]
    L += [f"**Mes joueurs** : {len(my_ups)} montée(s), {len(my_downs)} descente(s) · "
          f"**Tous** : {len(ups)} montée(s), {len(downs)} descente(s) sur {len(current)} joueurs suivis.", ""]
    if owned:
        L += ["## 🎯 Mes joueurs", ""]
        if my_ups:
            L += ["### ⬆️ Montées", ""] + change_table(my_ups, owned)
        if my_downs:
            L += ["### ⬇️ Descentes", ""] + change_table(my_downs, owned)
        if not (my_ups or my_downs):
            L += ["Aucun changement pour tes joueurs aujourd'hui.", ""]
    L += ["## 🌍 Tous les joueurs", "", "✅ = joueur que tu possèdes", ""]
    if ups:
        L += ["### ⬆️ Montées", ""] + change_table(ups, owned)
    if downs:
        L += ["### ⬇️ Descentes", ""] + change_table(downs, owned)
    if not (ups or downs):
        L += ["Aucun changement aujourd'hui.", ""]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- dashboard

DASHBOARD_TEMPLATE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tiers Sorare Set</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--accent:#2f5bea;--up:#16834a;--down:#c2352b;--mine:#fff6d6}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1d1d21;--fg:#ececee;--muted:#9a9aa2;--line:#2c2c32;--accent:#7b9bff;--up:#4cc285;--down:#ff7a6e;--mine:#3a3320}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:20px 16px 8px;max-width:1100px;margin:auto}h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted)}
main{max-width:1100px;margin:auto;padding:0 16px 40px}
.tabs{display:flex;gap:6px;margin:12px 0}.tabs button{border:1px solid var(--line);background:var(--card);color:var(--fg);padding:7px 14px;border-radius:999px;cursor:pointer;font:inherit}
.tabs button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
.filters input,.filters select{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.filters input[type=search]{flex:1;min-width:180px}label.chk{display:flex;align-items:center;gap:6px;padding:0 6px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;color:var(--muted);cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card)}
tr.mine td{background:var(--mine)}a{color:var(--accent);text-decoration:none}
.t{display:inline-block;padding:1px 8px;border-radius:999px;border:1px solid var(--line);font-size:12px}
.up{color:var(--up);font-weight:600}.down{color:var(--down);font-weight:600}.count{color:var(--muted);margin:6px 2px}
</style></head><body>
<header><h1>Tiers Sorare Set</h1><div class="sub">Mis à jour le __DATE__ · __N__ joueurs suivis · __M__ joueurs possédés</div></header>
<main>
<div class="tabs"><button data-v="players" class="on">Joueurs</button><button data-v="changes">Changements récents</button></div>
<div class="filters">
<input type="search" id="q" placeholder="Rechercher un joueur ou un club">
<select id="lg"><option value="">Tous les championnats</option></select>
<select id="tr"><option value="">Tous les tiers</option></select>
<label class="chk"><input type="checkbox" id="mine"> Mes joueurs</label>
</div>
<div class="count" id="count"></div>
<div class="wrap"><table><thead id="th"></thead><tbody id="tb"></tbody></table></div>
</main>
<script>
const P=__PLAYERS__, H=__HISTORY__, TIERS=__TIERS__;
const lab=t=>t&&TIERS[t]?TIERS[t][0]:'Sans tier', rk=t=>t&&TIERS[t]?TIERS[t][1]:0;
let view='players', sortKey='tier', sortDir=-1;
const $=id=>document.getElementById(id);
[...new Set(P.map(p=>p.league))].sort().forEach(l=>$('lg').add(new Option(l,l)));
Object.keys(TIERS).sort((a,b)=>rk(b)-rk(a)).filter(t=>P.some(p=>p.tier===t)).forEach(t=>$('tr').add(new Option(lab(t),t)));
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pl=(slug,name)=>`<a href="https://sorare.com/football/players/${slug}" target="_blank" rel="noopener">${esc(name)}</a>`;
function match(o){const q=$('q').value.toLowerCase();
 return (!q||o.name.toLowerCase().includes(q)||o.club.toLowerCase().includes(q))&&(!$('lg').value||o.league===$('lg').value)&&(!$('mine').checked||o.owned);}
function render(){
 if(view==='players'){
  const cols=[['name','Joueur'],['club','Club'],['league','Championnat'],['pos','Poste'],['tier','Tier'],['since','Depuis']];
  $('th').innerHTML='<tr>'+cols.map(([k,l])=>`<th data-k="${k}">${l}${sortKey===k?(sortDir<0?' ↓':' ↑'):''}</th>`).join('')+'</tr>';
  let r=P.filter(p=>match(p)&&(!$('tr').value||p.tier===$('tr').value));
  r.sort((a,b)=>{const va=sortKey==='tier'?rk(a.tier):a[sortKey]||'',vb=sortKey==='tier'?rk(b.tier):b[sortKey]||'';return (va>vb?1:va<vb?-1:a.name.localeCompare(b.name))*sortDir;});
  $('count').textContent=r.length+' joueurs';
  $('tb').innerHTML=r.map(p=>`<tr class="${p.owned?'mine':''}"><td>${pl(p.slug,p.name)}${p.owned?' ✅':''}</td><td>${esc(p.club)}</td><td>${esc(p.league)}</td><td>${esc(p.pos||'')}</td><td><span class="t">${lab(p.tier)}</span></td><td>${p.since||''}</td></tr>`).join('');
  document.querySelectorAll('#th th').forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=sortKey===k?-sortDir:(k==='tier'||k==='since'?-1:1);sortKey=k;render();});
 } else {
  $('th').innerHTML='<tr><th>Date</th><th>Joueur</th><th>Club</th><th>Championnat</th><th>Avant</th><th>Après</th></tr>';
  let r=H.filter(h=>match(h)&&(!$('tr').value||h.new===$('tr').value||h.old===$('tr').value));
  $('count').textContent=r.length+' changements (30 derniers jours)';
  $('tb').innerHTML=r.map(h=>{const up=rk(h.new)>rk(h.old);return `<tr class="${h.owned?'mine':''}"><td>${h.date}</td><td>${pl(h.slug,h.name)}${h.owned?' ✅':''}</td><td>${esc(h.club)}</td><td>${esc(h.league)}</td><td>${lab(h.old)}</td><td class="${up?'up':'down'}">${up?'▲':'▼'} ${lab(h.new)}</td></tr>`}).join('');
 }}
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{view=b.dataset.v;document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x===b));render();});
['q','lg','tr','mine'].forEach(id=>$(id).addEventListener('input',render));
render();
</script></body></html>
"""


def build_dashboard(today, current, owned):
    players = [dict(slug=s, owned=s in owned, **{k: p.get(k) for k in ("name", "club", "league", "pos", "tier", "since")})
               for s, p in current.items()]
    cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
    history = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["date"] >= cutoff:
                    history.append({"date": r["date"], "slug": r["slug"], "name": r["joueur"], "club": r["club"],
                                    "league": r["championnat"], "old": r["ancien_tier"] or None,
                                    "new": r["nouveau_tier"] or None, "owned": r["slug"] in owned})
    history.sort(key=lambda h: h["date"], reverse=True)
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (DASHBOARD_TEMPLATE.replace("__DATE__", today).replace("__N__", str(len(players)))
            .replace("__M__", str(sum(p["owned"] for p in players)))
            .replace("__PLAYERS__", dump(players)).replace("__HISTORY__", dump(history))
            .replace("__TIERS__", dump(TIERS)))
    os.makedirs(os.path.dirname(DASHBOARD_PATH), exist_ok=True)
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)


# --------------------------------------------------------------------------- run

def main():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    today = dt.date.today().isoformat()

    current = fetch_all_players(cfg["competitions"])
    owned, my_set = {}, None
    if cfg.get("sorare_user"):
        owned, my_set = fetch_my_players(cfg["sorare_user"].lower(), cfg.get("set_slug", "auto"))
    for s in cfg.get("extra_my_players", []):
        owned.setdefault(s, 1)

    previous = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            previous = json.load(f)
    first_run = not previous

    ups, downs = [], []
    for slug, p in current.items():
        old = previous.get(slug)
        if old is None:  # nouveau dans les championnats suivis (transfert, promotion…) : pas une évolution de tier
            p["since"] = today
        elif old.get("tier") != p["tier"]:
            p["since"] = today
            (ups if rank(p["tier"]) > rank(old.get("tier")) else downs).append((slug, old.get("tier"), p))
        else:
            p["since"] = old.get("since", today)

    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=1, sort_keys=True)

    new_file = not os.path.exists(HISTORY_PATH)
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(HISTORY_HEADER)
        for slug, old, p in ups + downs:
            w.writerow([today, slug, p["name"], p["club"], p["league"], old or "", p["tier"] or "",
                        "oui" if slug in owned else ""])

    report = build_report(today, current, previous, owned, first_run, ups, downs)
    if my_set:
        report = report.replace("\n\n", f"\n\n_Mes joueurs = joueurs dont j'ai une carte du Set « {my_set} »._\n\n", 1)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    build_dashboard(today, current, owned)
    print(report)

    my_changes = sum(1 for r in ups + downs if r[0] in owned)
    notify = cfg.get("notify", "all")
    changed = first_run or (bool(ups or downs) if notify == "all" else my_changes > 0)
    title = (f"Sorare Set : état de référence — {today}" if first_run else
             f"Sorare Set {today} — mes joueurs : {my_changes} changement(s) · tous : {len(ups)}⬆️ {len(downs)}⬇️")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"changed={'true' if changed else 'false'}\ntitle={title}\n")


if __name__ == "__main__":
    main()
