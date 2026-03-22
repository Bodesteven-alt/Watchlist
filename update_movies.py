import json
import os
import re
from typing import Dict, List, Optional

REFERENCE_FILE = "watchlist_reference.txt"
OUTPUT_FILE = "movies.json"


def normalize_title(title: str) -> str:
    t = (title or "").strip().lower()
    t = re.sub(r"^\d+\.\s*", "", t)
    t = re.sub(r"\([^)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\b(19|20)\d{2}\b", "", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_movie_line(line: str) -> Optional[Dict]:
    line = line.strip()

    # Standard format:
    # 1. Movie Title [2024, Genre, Genre]
    match = re.match(r"^\d+\.\s+(.*?)\s+\[(.*?)\]\s*$", line)
    if not match:
        return None

    title = match.group(1).strip()
    raw_details = match.group(2).strip()

    parts = [x.strip() for x in raw_details.split(",") if x.strip()]
    year = ""
    genres: List[str] = []

    for part in parts:
        if re.fullmatch(r"\d{4}", part):
            year = part
        else:
            genres.append(part)

    return {
        "title": title,
        "year": year,
        "year_num": int(year) if year.isdigit() else 0,
        "genres": ", ".join(genres),
    }


def split_sections(text: str) -> Dict[str, List[Dict]]:
    current = None
    sections = {
        "letterboxd": [],
        "imdb": [],
        "overlaps": [],
        "only_letterboxd": [],
        "only_imdb": [],
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if "LETTERBOXD MOVIES, ALPHABETICAL" in line:
            current = "letterboxd"
            continue
        if "IMDB MOVIES FROM CSV, ALPHABETICAL" in line:
            current = "imdb"
            continue
        if "OVERLAPS, ALPHABETICAL" in line:
            current = "overlaps"
            continue
        if "ONLY IN LETTERBOXD" in line:
            current = "only_letterboxd"
            continue
        if "ONLY IN IMDB" in line:
            current = "only_imdb"
            continue

        if not current:
            continue

        movie = parse_movie_line(line)
        if movie:
            sections[current].append(movie)

    return sections


def build_movies(sections: Dict[str, List[Dict]]) -> List[Dict]:
    merged: Dict[str, Dict] = {}

    for movie in sections["letterboxd"]:
        norm = normalize_title(movie["title"])
        merged[norm] = {
            "title": movie["title"],
            "year": movie["year"],
            "year_num": movie["year_num"],
            "genres": movie["genres"],
            "on_imdb": False,
            "on_letterboxd": True,
            "is_overlap": False,
        }

    for movie in sections["imdb"]:
        norm = normalize_title(movie["title"])
        if norm in merged:
            merged[norm]["on_imdb"] = True
            merged[norm]["is_overlap"] = True

            if not merged[norm]["year"] and movie["year"]:
                merged[norm]["year"] = movie["year"]
                merged[norm]["year_num"] = movie["year_num"]

            if not merged[norm]["genres"] and movie["genres"]:
                merged[norm]["genres"] = movie["genres"]
        else:
            merged[norm] = {
                "title": movie["title"],
                "year": movie["year"],
                "year_num": movie["year_num"],
                "genres": movie["genres"],
                "on_imdb": True,
                "on_letterboxd": False,
                "is_overlap": False,
            }

    movies = sorted(merged.values(), key=lambda x: x["title"].lower())
    return movies


def main() -> None:
    if not os.path.isfile(REFERENCE_FILE):
        print(f"Missing file: {REFERENCE_FILE}")
        return

    with open(REFERENCE_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    sections = split_sections(text)
    movies = build_movies(sections)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(movies)} movies to {OUTPUT_FILE}")
    print(f"Letterboxd parsed: {len(sections['letterboxd'])}")
    print(f"IMDb parsed: {len(sections['imdb'])}")
    print(f"Overlaps parsed: {len(sections['overlaps'])}")


if __name__ == "__main__":
    main()
