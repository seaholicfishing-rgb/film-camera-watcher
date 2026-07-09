#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中古フィルムカメラ 新着検知 → Chatwork通知

- Shopify系ショップの /products.json を取得
- config.json のフィルタで「フィルム関連のみ・価格足切り」を適用
- 前回からの新着(差分)だけを Chatwork へまとめて1通通知
- state.json に通知済み商品IDを保存（重複通知ゼロ・取りこぼしゼロ）
- 初回はサイレント記録（既存在庫を一気に通知しない）

依存ライブラリなし（Python標準ライブラリのみ）。
"""
import os
import re
import sys
import json
import datetime
import pathlib
import urllib.request
import urllib.parse

ROOT = pathlib.Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
CHATWORK_API = "https://api.chatwork.com/v2"


def log(*a):
    print("[watcher]", *a, flush=True)


def jst_now():
    # 日本は夏時間なし → UTC+9 固定でOK
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as e:
        log("読み込み失敗:", path, e)
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def http_get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (film-camera-watcher)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ---------- 取得アダプタ（店のタイプごと）----------

def fetch_shopify(shop):
    """Shopify の /products.json から商品リストを取得し、新着順に並べて返す"""
    base = shop["url"].rstrip("/")
    data = json.loads(http_get(f"{base}/products.json?limit=250"))
    out = []
    for p in data.get("products", []):
        try:
            price = int(float(p["variants"][0]["price"]))
        except Exception:
            price = 0
        mount = ""
        for t in p.get("tags", []):
            if str(t).startswith("マウント_"):
                mount = str(t).split("_", 1)[1]
                break
        out.append({
            "id": str(p["id"]),
            "title": p.get("title", "(無題)"),
            "price": price,
            "url": f"{base}/products/{p.get('handle', '')}",
            "tags": [str(t) for t in p.get("tags", [])],
            "mount": mount,
            "created_at": p.get("created_at", ""),
        })
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


def fetch_fujiya(shop):
    """フジヤカメラの中古フィルムカメラ一覧（HTML/UTF-8）。
    フィルム専用カテゴリ(rC-FCMU)なのでデジタル混在なし→価格足切りのみでOK。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/shop/r/rC-FCMU_s1/?ps=50")  # _s1=新着順
    html = http_get(base + path).decode("utf-8", "replace")
    out = []
    for b in html.split("js-enhanced-ecommerce-item")[1:]:
        mid = re.search(r'/shop/g/(gC\d+)/', b)
        mprice = re.search(r'￥([0-9,]+)', b)
        if not (mid and mprice):
            continue
        pid = mid.group(1)
        mname = re.search(r'/shop/g/gC\d+/"\s+title="([^"]+)"', b)
        out.append({
            "id": pid,
            "title": mname.group(1) if mname else "(無題)",
            "price": int(mprice.group(1).replace(",", "")),
            "url": f"{base}/shop/g/{pid}/",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_makeshop(shop):
    """MakeShop系（三宝カメラ等・EUC-JP）。/shopbrand/all_items/ が新着順(商品ID降順)。
    この系統はフィルム/デジタルを区別しないため、デジタル込みで価格足切りのみ適用する。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/shopbrand/all_items/")
    enc = shop.get("encoding", "euc-jp")
    html = http_get(base + path).decode(enc, "replace")
    out = []
    seen = set()
    # 商品名は画像のalt属性に入る（三宝・富士越などMakeShop系で共通）。
    # 商品リンク直後の<img ... alt="商品名">を拾い、近傍の「○○円」を価格とする。
    for m in re.finditer(r'/shopdetail/(\d+)/[^"]*">\s*<img[^>]*alt="([^"]+)"', html):
        pid, name = m.group(1), m.group(2).strip()
        if pid in seen or not name:
            continue
        seen.add(pid)
        seg = html[m.end():m.end() + 2000]
        pm = re.search(r'([0-9,]+)\s*円', seg)
        out.append({
            "id": pid,
            "title": name,
            "price": int(pm.group(1).replace(",", "")) if pm else 0,
            "url": f"{base}/shopdetail/{pid}/",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_oscamera(shop):
    """OSカメラサービスの新着ページ(FrontPage系HTML)。商品名/価格はテーブルがグリッド構造で
    対応付けが困難なため、サムネ画像名の商品コード(例 A-0323)の新規出現で新着を検知する。
    価格は取得しないので 0（＝価格足切りせず全件通知）。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/new-product.html")
    html = http_get(base + path).decode("utf-8", "replace")
    out = []
    seen = set()
    for m in re.finditer(r'thumbnail/([^/"]+?)a\.(?:jpg|JPG)', html):
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        out.append({
            "id": code,
            "title": f"新着コード {code}（ページで確認）",
            "price": 0,
            "url": base + path,
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_akasaka(shop):
    """アカサカカメラの新入荷ページ。各商品に /product/view/ID(数値ID＝商品ページ)・品名・
    価格(NN,NNN円)。フィルム/デジタル無区別＋価格応談/売約の品もあるため、価格足切りせず
    新着を全件通知する（価格は取得できた時だけ表示）。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/product.html")
    html = http_get(base + path).decode("utf-8", "replace")
    out = []
    seen = set()
    prev = 0
    for m in re.finditer(r'/product/view/(\d+)">([^<]+)</a>', html):
        pid, name = m.group(1), m.group(2).strip()
        seg = html[prev:m.start()]
        prev = m.end()
        if pid in seen or not name:
            continue
        seen.add(pid)
        pm = re.findall(r'price en">\s*([0-9,]+)', seg)
        price = int(pm[-1].replace(",", "")) if pm else 0
        out.append({
            "id": pid, "title": name,
            "price": price,
            "url": f"{base}/product/view/{pid}",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_saito(shop):
    """サイトウカメラ(saito-camera.com)の一覧(EUC-JP)。各商品は
    <tr onclick="location.href='det.php?id=NNNNN'"> の行で、セルが
    [画像, メーカー, 品名, 価格(&yen;NN,NNN), 程度, 備考] の並び。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/list.php?ct=3&w=&mk=&cd=2")
    html = http_get(base + path).decode("euc-jp", "replace")
    out = []
    seen = set()
    for m in re.finditer(r"location\.href='det\.php\?id=(\d+)'\">(.*?)</tr>", html, re.S):
        pid, row = m.group(1), m.group(2)
        if pid in seen:
            continue
        seen.add(pid)
        cells = [re.sub(r'<[^>]+>', '', t).replace('&nbsp;', ' ').strip()
                 for t in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        maker = cells[1] if len(cells) > 1 else ""
        name = cells[2] if len(cells) > 2 else ""
        title = (maker + " " + name).strip() or "(無題)"
        price = 0
        if len(cells) > 3:
            pm = re.search(r'([0-9,]+)', cells[3])
            if pm:
                price = int(pm.group(1).replace(",", ""))
        out.append({
            "id": pid, "title": title, "price": price,
            "url": f"{base}/det.php?id={pid}",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_cameracollection(shop):
    """カメラコレクション(camera-collection.jp/itemlist/、WordPress/VK)。商品カードは
    vk_post_titleに品名、本文に「価格(税込)NN,NNN円」。価格の無いカード(=お知らせ記事)は
    商品ではないので除外する。商品IDはURLスラッグ。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/itemlist/")
    html = http_get(base + path).decode("utf-8", "replace")
    firstpos = []
    seen = set()
    for m in re.finditer(r'/itemlist/([a-z0-9][^"/]{14,})/', html):
        s = m.group(1)
        if s in seen:
            continue
        seen.add(s)
        firstpos.append((s, m.start()))
    out = []
    for i, (slug, pos) in enumerate(firstpos):
        end = firstpos[i + 1][1] if i + 1 < len(firstpos) else pos + 2500
        card = html[pos:end]
        tm = re.search(r'vk_post_title[^>]*>(.*?)</', card, re.S)
        name = re.sub(r'<[^>]+>', '', tm.group(1)).strip() if tm else ''
        name = re.sub(r'\s*新着!+\s*$', '', name).strip()
        ctext = re.sub(r'<[^>]+>', ' ', card)
        pm = re.search(r'税込[^0-9]{0,12}([0-9,]+)\s*円', ctext)
        if not pm or not name:   # 価格なし＝お知らせ記事 → 除外
            continue
        out.append({
            "id": slug,
            "title": name,
            "price": int(pm.group(1).replace(",", "")),
            "url": f"{base}/itemlist/{slug}/",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


def fetch_naniwa(shop):
    """ナニワグループオンライン(cameranonaniwa.jp、レモン社含む。Shift_JIS/MakeShop系)。
    各商品リンク /shop/g/gID/ の title属性に品名、後続に「￥NN,NNN(税込)」。"""
    base = shop["url"].rstrip("/")
    path = shop.get("listing_path", "/shop/e/ezaiko/")
    html = http_get(base + path).decode("shift_jis", "replace")
    ms = list(re.finditer(r'/shop/g/(g\d+)/"\s+title="([^"]+)"', html))
    out = []
    seen = set()
    for i, m in enumerate(ms):
        pid, name = m.group(1), m.group(2).strip()
        if pid in seen:
            continue
        seen.add(pid)
        end = ms[i + 1].start() if i + 1 < len(ms) else m.end() + 2500
        seg = html[m.end():end]
        pm = re.search(r'([0-9,]+)\s*[\(（]税込', seg)
        out.append({
            "id": pid,
            "title": name,
            "price": int(pm.group(1).replace(",", "")) if pm else 0,
            "url": f"{base}/shop/g/{pid}/",
            "tags": [], "mount": "", "created_at": "",
        })
    return out


FETCHERS = {"shopify": fetch_shopify, "fujiya": fetch_fujiya,
            "makeshop": fetch_makeshop, "oscamera": fetch_oscamera,
            "akasaka": fetch_akasaka, "saito": fetch_saito,
            "cameracollection": fetch_cameracollection, "naniwa": fetch_naniwa}


# ---------- フィルタ（通知する／しない）----------

def classify_and_filter(item, f):
    """(通知するか, ラベル) を返す。ラベル例: カメラ / レンズ / アクセサリ / 要確認"""
    # フラット価格モード：在庫が全てフィルム関連で揃っている店（例フジヤのフィルム専用一覧）
    # はカテゴリ判定不要、価格足切りだけで判定する
    if "flat_min_price" in f:
        if item["price"] >= f["flat_min_price"]:
            return (True, f.get("label", "新着"))
        return (False, None)

    tags = set(item["tags"])

    # デジタル本体・AFレンズ など 完全除外カテゴリ
    if tags & set(f.get("exclude_category_tags", [])):
        return (False, None)

    # デジタル専用マウントのレンズを除外
    if item["mount"] and item["mount"] in set(f.get("exclude_mounts", [])):
        return (False, None)

    price = item["price"]
    for key, rule in f.get("price_rules", {}).items():
        if tags & set(rule.get("categories", [])):
            if price >= rule.get("min_price", 0):
                return (True, rule.get("label", key))
            return (False, None)  # カテゴリは該当するが価格が足切り未満

    # どのカテゴリにも該当しない＝判別不能 → 取りこぼし防止で通知（要確認マーク）
    if f.get("notify_unknown", True):
        return (True, "要確認")
    return (False, None)


def yen(n):
    return "￥{:,}".format(n)


def build_message(shop_name, items, mention_ids=None):
    lines = []
    # 自分宛てメンションを付けると Chatwork が通知音/バッジを鳴らす
    if mention_ids:
        lines.append("".join(f"[To:{m}]" for m in mention_ids))
    lines.append(f"[info][title]📷 新着 {len(items)}件 / {shop_name}[/title]")
    for it in items:
        if it["_label"] == "要確認":
            mark = "⚠️要確認 "
        else:
            mark = f"[{it['_label']}] "
        price_part = f"　{yen(it['price'])}" if it["price"] > 0 else ""
        lines.append(f"・{mark}{it['title']}{price_part}\n　{it['url']}")
    lines.append("[/info]")
    return "\n".join(lines)


def chatwork_post(room_id, body, token):
    data = urllib.parse.urlencode({"body": body}).encode()
    req = urllib.request.Request(
        f"{CHATWORK_API}/rooms/{room_id}/messages",
        data=data, headers={"X-ChatWorkToken": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    cfg = load_json(CONFIG_PATH, None)
    if not cfg:
        log("config.json が読めません。終了します。")
        sys.exit(1)

    # 稼働時間ガード（JST）。手動実行(FORCE_RUN=1)時はスキップ
    if os.environ.get("FORCE_RUN") != "1":
        ah = cfg.get("active_hours", {})
        hour = jst_now().hour
        if not (ah.get("start", 0) <= hour <= ah.get("end", 23)):
            log(f"稼働時間外（JST {hour}時）のため何もせず終了。")
            return

    token = os.environ.get("CHATWORK_TOKEN")  # 投稿時のみ必須
    # ルームID・メンション先は公開リポに出さないため環境変数(GitHub Secrets)優先。
    # 無ければconfig.jsonの値にフォールバック（ローカル実行用）。
    room_id = os.environ.get("CHATWORK_ROOM_ID") or str(cfg.get("chatwork", {}).get("room_id", ""))

    state = load_json(STATE_PATH, {})

    for shop in cfg.get("shops", []):
        name = shop["name"]
        fetch = FETCHERS.get(shop["type"])
        if not fetch:
            log(f"未対応タイプ: {shop['type']}（{name}）スキップ")
            continue
        try:
            items = fetch(shop)
        except Exception as e:
            log(f"[{name}] 取得失敗: {e}")
            continue

        is_first = name not in state
        seen = set(state.get(name, {}).get("seen_ids", []))
        current_ids = [it["id"] for it in items]

        new_notify = []
        if not is_first:
            for it in items:
                if it["id"] in seen:
                    continue
                ok, label = classify_and_filter(it, shop.get("filters", {}))
                if ok:
                    it["_label"] = label
                    new_notify.append(it)

        # 状態更新（取得できた全IDをseenに記録）
        merged_seen = sorted(set(list(seen) + current_ids))
        state[name] = {
            "seen_ids": merged_seen,
            "updated_at": jst_now().isoformat(timespec="seconds"),
        }

        if is_first:
            log(f"[{name}] 初回サイレント記録: {len(current_ids)}件をseen登録（通知なし）")
            continue

        if not new_notify:
            log(f"[{name}] 新着なし")
            continue

        if not token:
            log(f"[{name}] 新着{len(new_notify)}件ありますが CHATWORK_TOKEN 未設定のため未通知。"
                f"次回再通知できるようseenを巻き戻します。")
            state[name]["seen_ids"] = sorted(seen)
            continue

        new_notify.sort(key=lambda x: -x["price"])  # 高い順
        env_mentions = os.environ.get("CHATWORK_MENTION_IDS", "")
        mention_ids = ([x.strip() for x in env_mentions.split(",") if x.strip()]
                       or cfg.get("chatwork", {}).get("mention_account_ids", []))
        body = build_message(name, new_notify, mention_ids)
        try:
            res = chatwork_post(room_id, body, token)
            log(f"[{name}] 新着 {len(new_notify)}件を通知 (message_id={res.get('message_id')})")
        except Exception as e:
            log(f"[{name}] 通知失敗: {e} → seenを巻き戻して次回再試行")
            state[name]["seen_ids"] = sorted(seen)

    save_json(STATE_PATH, state)
    log("完了")


if __name__ == "__main__":
    main()
