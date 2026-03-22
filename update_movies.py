import csv
import glob
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LETTERBOXD_URL = "https://letterboxd.com/miscalim/watchlist/"
LETTERBOXD_USERNAME = "miscalim"
LETTERBOXD_BASE = "https://letterboxd.com"

SEARCH_FOLDERS = [
    ".",
    "/storage/emulated/0/Download",
    "/sdcard/Download",
]

CSV_PATTERNS = [
    "*watchlist*.csv",
    "*imdb*.csv",
    "*.csv",
]

OUTPUT_FILE = "movies.json"
TMP_OUTPUT_FILE = "movies.tmp.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_title(title: str) -> str:
    t = (title or "").strip().lower()
    t = re.sub(r"^\d+\.\s*", "", t)
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\b(19|20)\d{2}\b", "", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def sort_movies(movies):
    return sorted(movies, key=lambda x: x["title"].lower())


def safe_get(url: str, timeout: int = 20):
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.RequestException as e:
        print(f"[Request failed] {url} -> {e}")
        return None


def try_find_film_url_from_img(img):
    a = img.find_parent("a", href=True)
    if a:
        href = (a.get("href") or "").strip()
        if "/film/" in href:
            return urljoin(LETTERBOXD_BASE, href.split("?")[0])

    for ancestor in img.parents:
        attrs = getattr(ancestor, "attrs", None)
        if not attrs:
            continue

        data_target_link = attrs.get("data-target-link", "")
        if data_target_link and "/film/" in data_target_link:
            return urljoin(LETTERBOXD_BASE, data_target_link.split("?")[0])

        href = attrs.get("href", "")
        if href and "/film/" in href:
            return urljoin(LETTERBOXD_BASE, href.split("?")[0])

    return ""


def extract_letterboxd_entries_from_page(soup, username_to_exclude=""):
    entries = []
    seen = set()
    excluded_norm = normalize_title(username_to_exclude) if username_to_exclude else ""

    for img in soup.find_all("img", alt=True):
        title = (img.get("alt") or "").strip()
        if not title:
            continue

        norm = normalize_title(title)
        if not norm:
            continue
        if norm == "letterboxd":
            continue
        if excluded_norm and norm == excluded_norm:
            continue
        if norm in seen:
            continue

        seen.add(norm)
        entries.append({
            "title": title,
            "film_url": try_find_film_url_from_img(img),
        })

    return entries


def scrape_letterboxd_film_details(film_url: str):
    year = ""
    genres = ""

    if not film_url:
        return year, genres

    response = safe_get(film_url, timeout=20)
    if response is None or response.status_code != 200:
        return year, genres

    try:
        soup = BeautifulSoup(response.text, "html.parser")

        year_link = soup.find("a", href=re.compile(r"/year/\d{4}/"))
        if year_link:
            y = year_link.get_text(" ", strip=True)
            if re.fullmatch(r"\d{4}", y):
                year = y

        if not year:
            text = soup.get_text(" ", strip=True)
            match = re.search(r"\b(18|19|20)\d{2}\b", text)
            if match:
                year = match.group(0)

        genre_links = soup.find_all("a", href=re.compile(r"/films/genre/"))
        genre_list = []
        seen = set()

        for g in genre_links:
            gt = g.get_text(" ", strip=True)
            gt = re.sub(r"\s+", " ", gt).strip()
            if not gt:
                continue
            low = gt.lower()
            if low in seen:
                continue
            seen.add(low)
            genre_list.append(gt)

        if genre_list:
            genres = ", ".join(genre_list)

    except Exception as e:
        print(f"[Letterboxd detail parse failed] {film_url} -> {e}")

    return year, genres


def get_letterboxd_movies(base_url, username_to_exclude=""):
    movies = []
    page = 1
    known_norms = set()

    print("[Start] Scraping Letterboxd")

    while True:
        url = base_url if page == 1 else base_url.rstrip("/") + f"/page/{page}/"
        print(f"[Letterboxd] Checking page {page}: {url}")

        response = safe_get(url, timeout=20)
        if response is None:
            print("[Letterboxd] Request failed, stopping.")
            break

        if response.status_code != 200:
            print(f"[Letterboxd] Stopped, status {response.status_code}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        page_entries = extract_letterboxd_entries_from_page(
            soup,
            username_to_exclude=username_to_exclude
        )

        if not page_entries:
            print("[Letterboxd] No more titles found, stopping.")
            break

        new_count = 0
        for entry in page_entries:
            norm = normalize_title(entry["title"])
            if norm in known_norms:
                continue

            known_norms.add(norm)
            movies.append({
                "title": entry["title"],
                "year": "",
                "year_num": 0,
                "genres": "",
                "on_imdb": False,
                "on_letterboxd": True,
                "is_overlap": False,
                "film_url": entry["film_url"],
            })
            new_count += 1

        print(f"[Letterboxd] Found {new_count} new titles on page {page}")

        if new_count == 0:
            print("[Letterboxd] No new titles added, stopping.")
            break

        page += 1
        time.sleep(1)

    got_urls = len([m for m in movies if m.get("film_url")])
    print(f"[Letterboxd] Found detail page URLs for {got_urls} of {len(movies)} films")

    if got_urls:
        print(f"[Letterboxd] Fetching details for {got_urls} films")

    for idx, movie in enumerate(movies, start=1):
        if movie.get("film_url"):
            year, genres = scrape_letterboxd_film_details(movie["film_url"])
            movie["year"] = year
            movie["year_num"] = int(year) if year.isdigit() else 0
            movie["genres"] = genres

        if idx % 10 == 0 or idx == len(movies):
            print(f"[Letterboxd Details] {idx}/{len(movies)}")

        time.sleep(0.3)

    for movie in movies:
        movie.pop("film_url", None)

    return sort_movies(movies)


def find_newest_csv():
    candidates = []

    for folder in SEARCH_FOLDERS:
        if not os.path.isdir(folder):
            continue

        for pattern in CSV_PATTERNS:
            full_pattern = os.path.join(folder, pattern)
            for path in glob.glob(full_pattern):
                if os.path.isfile(path):
                    candidates.append(path)

    if not candidates:
        return None

    candidates = sorted(candidates, key=os.path.getmtime, reverse=True)
    return candidates[0]


def parse_imdb_csv(csv_path):
    if not csv_path:
        return []

    print("[Start] Looking for newest IMDb CSV")
    print(f"[IMDb CSV] Using file: {csv_path}")

    movies = []

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    print(f"[IMDb CSV] Columns found: {fieldnames}")

    if not rows:
        return []

    title_field = "Title" if "Title" in fieldnames else None
    year_field = "Year" if "Year" in fieldnames else None
    genres_field = "Genres" if "Genres" in fieldnames else None

    if not title_field:
        print("[IMDb CSV] Could not find a Title column.")
        return []

    seen = set()

    for row in rows:
        title = (row.get(title_field) or "").strip()
        year = (row.get(year_field) or "").strip() if year_field else ""
        genres = (row.get(genres_field) or "").strip() if genres_field else ""

        norm = normalize_title(title)
        if norm and norm not in seen:
            seen.add(norm)
            movies.append({
                "title": title,
                "year": year,
                "year_num": int(year) if year.isdigit() else 0,
                "genres": genres,
                "on_imdb": True,
                "on_letterboxd": False,
                "is_overlap": False,
            })

    return sort_movies(movies)


def merge_movies(letterboxd_movies, imdb_movies):
    merged = {}

    for movie in letterboxd_movies:
        norm = normalize_title(movie["title"])
        if norm:
            merged[norm] = dict(movie)

    for movie in imdb_movies:
        norm = normalize_title(movie["title"])
        if not norm:
            continue

        if norm in merged:
            existing = merged[norm]
            existing["on_imdb"] = True
            existing["is_overlap"] = True

            if not existing.get("year") and movie.get("year"):
                existing["year"] = movie["year"]
                existing["year_num"] = movie.get("year_num", 0)

            if not existing.get("genres") and movie.get("genres"):
                existing["genres"] = movie["genres"]
        else:
            merged[norm] = dict(movie)

    return sort_movies(list(merged.values()))


def validate_movies(movies):
    if not isinstance(movies, list):
        return False
    if len(movies) == 0:
        return False

    required = {"title", "year", "year_num", "genres", "on_imdb", "on_letterboxd", "is_overlap"}
    for movie in movies[:5]:
        if not required.issubset(set(movie.keys())):
            return False

    return True


def load_existing_movies():
    if not os.path.isfile(OUTPUT_FILE):
        return []

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception as e:
        print(f"[Load existing movies failed] {e}")

    return []


def save_movies(movies):
    with open(TMP_OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)

    os.replace(TMP_OUTPUT_FILE, OUTPUT_FILE)


def main():
    existing_movies = load_existing_movies()

    letterboxd_movies = []
    imdb_movies = []

    try:
        letterboxd_movies = get_letterboxd_movies(LETTERBOXD_URL, LETTERBOXD_USERNAME)
    except Exception as e:
        print(f"[Letterboxd scrape failed] {e}")

    try:
        csv_path = find_newest_csv()
        imdb_movies = parse_imdb_csv(csv_path) if csv_path else []
        if not csv_path:
            print("[IMDb CSV] No CSV file found.")
    except Exception as e:
        print(f"[IMDb parse failed] {e}")

    merged_movies = merge_movies(letterboxd_movies, imdb_movies)

    if validate_movies(merged_movies):
        save_movies(merged_movies)
        print(f"[Success] Wrote {len(merged_movies)} movies to {OUTPUT_FILE}")
        return 0

    if validate_movies(existing_movies):
        print("[Fallback] New scrape was not valid, keeping existing movies.json")
        return 0

    print("[Failure] No valid new data and no valid existing movies.json")
    return 1


if __name__ == "__main__":
    sys.exit(main())
