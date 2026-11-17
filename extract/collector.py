from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, TypedDict, Union

import requests
from bs4 import BeautifulSoup
from requests import Response, Session

# --- ตั้งค่าตรงนี้ ---
ROOT: Path = Path(__file__).resolve().parent.parent
INPUT_TXT: Path = ROOT / "seed" / "all_appids.txt"
OUTPUT_FILE: Path = ROOT / "raw" / "steam.jsonl"
AUTH_FILE: Path = ROOT / "config" / "steam_auth.json"

DELAY_MIN: float = 0.8
DELAY_MAX: float = 2.0
WORKERS: int = 100
file_lock: threading.Lock = threading.Lock()
thread_local: threading.local = threading.local()

COOKIES: Dict[str, str] = {
    "birthtime": "946684800",
    "mature_content": "1",
    "lastagecheckage": "1-January-2000",
}

HEADERS: Dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "th-TH,th;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ============================================================
# 0. Types กลาง
# ============================================================
class GameData(TypedDict, total=False):
    app_id: str
    url: str
    name: str
    release_date: str
    developer: str
    publisher: str
    genre: str
    tags: List[str]
    price_main: str

# Extractor = function ที่รับ soup แล้ว return str หรือ List[str]
Extractor = Callable[[BeautifulSoup], Union[str, List[str]]]

# ============================================================
# 1. Helpers พื้นฐาน (ใช้ซ้ำในทุก extractor)
# ============================================================
def txt(soup: BeautifulSoup, sel: str) -> str:
    el = soup.select_one(sel)
    return el.get_text(strip=True) if el else ""

def txt_all(soup: BeautifulSoup, sel: str) -> List[str]:
    return [el.get_text(strip=True) for el in soup.select(sel) if el.get_text(strip=True)]

def get_session() -> Session:
    if not hasattr(thread_local, "session"):
        s: Session = requests.Session()
        s.headers.update(HEADERS)
        for k, v in COOKIES.items():
            s.cookies.set(k, v, domain=".steampowered.com", path="/")
        if AUTH_FILE.exists():
            try:
                auth: Dict[str, object] = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
                cookies: List[Dict[str, str]] = auth.get("cookies", [])  # type: ignore[assignment]
                for c in cookies:
                    s.cookies.set(
                        c["name"],
                        c["value"],
                        domain=c.get("domain", ".steampowered.com"),
                        path=c.get("path", "/"),
                    )
            except Exception:
                pass
        thread_local.session = s
    return thread_local.session  # type: ignore[no-any-return]

def load_app_ids() -> List[str]:
    text: str = INPUT_TXT.read_text(encoding="utf-8")
    ids: List[str] = [line.strip() for line in text.splitlines() if line.strip().isdigit()]
    return ids

def load_done_ids() -> Set[str]:
    done: Set[str] = set()
    if OUTPUT_FILE.exists():
        for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
            try:
                row: Dict[str, object] = json.loads(line)
                done.add(str(row["app_id"]))
            except Exception:
                pass
    return done

# ============================================================
# 2. Extractors: 1 config = 1 function
#    รับ soup -> return ค่าของ config นั้นอย่างเดียว
# ============================================================
def extract_name(soup: BeautifulSoup) -> str:
    return txt(soup, "#appHubAppName")

def extract_release_date(soup: BeautifulSoup) -> str:
    return txt(soup, ".date")

def extract_genre(soup: BeautifulSoup) -> str:
    genres: List[str] = txt_all(soup, "#genresAndManufacturer a[href*='/genre/']")
    return genres[0] if genres else ""

def extract_developer(soup: BeautifulSoup) -> str:
    developers: List[str] = txt_all(soup, "#developers_list a")
    return developers[0] if developers else ""

def extract_publisher(soup: BeautifulSoup) -> str:
    publishers: List[str] = txt_all(soup, "#genresAndManufacturer a[href*='/publisher/']")
    if publishers:
        return publishers[0]
    return extract_developer(soup)

def extract_tags(soup: BeautifulSoup) -> List[str]:
    tags: List[str] = [t for t in txt_all(soup, ".app_tag") if t != "+"]
    return tags

def extract_price_main(soup: BeautifulSoup) -> str:
    final_el = soup.select_one(".discount_final_price")
    if final_el:
        return final_el.get_text(strip=True)
    price_el = soup.select_one(".game_purchase_price")
    if price_el:
        return price_el.get_text(strip=True)
    action_el = soup.select_one(".game_purchase_action")
    if action_el and "Free" in action_el.get_text():
        return "ฟรี"
    return ""

# --- ตัวอย่าง config ใหม่ในอนาคต ---
# def extract_description(soup: BeautifulSoup) -> str:
#     return txt(soup, ".game_description_snippet")
#
# def extract_review_summary(soup: BeautifulSoup) -> str:
#     return txt(soup, ".game_review_summary")

# ============================================================
# 3. Registry
# ============================================================
EXTRACTORS: Dict[str, Extractor] = {
    "name": extract_name,
    "release_date": extract_release_date,
    "developer": extract_developer,
    "publisher": extract_publisher,
    "genre": extract_genre,
    "tags": extract_tags,
    "price_main": extract_price_main,
    # "description": extract_description,
    # "review_summary": extract_review_summary,
}

# ============================================================
# 4. scrape_one
# ============================================================
def scrape_one(session: Session, app_id: str) -> Optional[GameData]:
    url: str = f"https://store.steampowered.com/app/{app_id}/?l=english&cc=US"
    res: Response = session.get(url, timeout=30, allow_redirects=True)

    if "agecheck" in res.url:
        return None
    if res.status_code != 200:
        return None

    soup: BeautifulSoup = BeautifulSoup(res.text, "html.parser")

    if not extract_name(soup):
        return None

    data: GameData = {"app_id": app_id, "url": url}
    for key, func in EXTRACTORS.items():
        try:
            value: Union[str, List[str]] = func(soup)
            # mypy จะบ่นตรงนี้ถ้า assign ตรงๆ เพราะ GameData มีหลาย type
            # ใช้ dict assignment แบบนี้เพื่อความง่าย
            data[key] = value  # type: ignore[literal-required]
        except Exception:
            data[key] = [] if key == "tags" else ""  # type: ignore[literal-required]

    return data

# ============================================================
# 5. Worker / Main
# ============================================================
def worker(worker_id: int, app_ids: List[str]) -> None:
    session: Session = get_session()

    for i, app_id in enumerate(app_ids, 1):
        try:
            data: Optional[GameData] = scrape_one(session, app_id)
            if data and data.get("name"):
                with file_lock:
                    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(data, ensure_ascii=False) + "\n")
                        f.flush()
                print(f"[W{worker_id}][{i}/{len(app_ids)}] ✅ {app_id} {data['name']} | {data['price_main']}")
            else:
                print(f"[W{worker_id}][{i}/{len(app_ids)}] ⏭ ข้าม {app_id} - ไม่มีหน้า / ถูกลบ")
        except requests.exceptions.Timeout:
            print(f"[W{worker_id}][{i}/{len(app_ids)}] ❌ {app_id} Timeout - พัก 30 วิ")
            time.sleep(30)
        except Exception as e:
            print(f"[W{worker_id}][{i}/{len(app_ids)}] ❌ {app_id} พัง: {e}")
            if "timeout" in str(e).lower():
                time.sleep(30)

        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        if i % 1000 == 0:
            print(f"[W{worker_id}] --- พัก 10 วิ หลังครบ {i} เกม ---")
            time.sleep(10)

def main() -> None:
    # สร้างโฟลเดอร์ที่ต้องใช้ก่อน กันพังตอนเขียนไฟล์
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)

    all_ids: List[str] = load_app_ids()
    done_ids: Set[str] = load_done_ids()
    todo: List[str] = [x for x in all_ids if x not in done_ids]

    print(f"ทั้งหมด: {len(all_ids)} | เก็บแล้ว: {len(done_ids)} | เหลือ: {len(todo)} | Workers: {WORKERS}")
    if not todo:
        print("เก็บครบแล้ว!")
        return

    chunks: List[List[str]] = [[] for _ in range(WORKERS)]
    for i, app_id in enumerate(todo):
        chunks[i % WORKERS].append(app_id)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = [ex.submit(worker, wid, chunk) for wid, chunk in enumerate(chunks)]
        for fut in futures:
            fut.result()

    print(f"เสร็จรอบนี้! ดูไฟล์ {OUTPUT_FILE}")

if __name__ == "__main__":
    main()