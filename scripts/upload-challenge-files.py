#!/usr/bin/env python3
"""
Upload downloadable challenge files to CTFd.
Maps each challenge's binary/zip/source to its CTFd challenge ID.
Safe to re-run — skips challenges that already have files attached.
"""
import os, sys, requests, json

CTFD_URL  = os.environ.get("CTFD_URL",   "http://127.0.0.1:8000")
CTFD_USER = os.environ.get("CTFD_USER",  "admin")
CTFD_PASS = os.environ.get("CTFD_PASS",  "admin")
CHALS_DIR = os.environ.get("CHALS_DIR",  os.path.join(os.path.dirname(__file__), "../../recruit-chals"))

# challenge name (as in CTFd) → list of file paths relative to recruit-chals root
FILES = {
    "overflow":           ["intro/overflow/chal/chal", "intro/overflow/src/main.c"],
    "pwntools":           ["intro/pwntools/client.py"],
    "POR":                ["pwn/POR/share.zip"],
    "UAF":                ["pwn/UAF/share.zip"],
    "Pivot":              ["pwn/pivot/share.zip"],
    "unsafe-linking":     ["pwn/unsafe-linking/share.zip"],
    "No Free Shells":     ["pwn/no_free_shells/no_free_shells"],
    "Simply Smashing":    ["pwn/simply_smashing/simply_smashing"],
    "stacking":           ["pwn/stacking/stacking"],
    "checker":            ["rev/checker/checker"],
    "go":                 ["rev/go/go"],
    "Postage":            ["rev/Postage/postage"],
    "rubiksCube":         ["rev/rubiksCube/share/cube"],
    "MasterChallenge":    ["rev/MasterChallenge/Challenge-Files/main"],
    "holes":              ["web/holes/dist/holes.zip"],
    "AES CBC":            ["crypto/aes_cbc/server.py"],
    "AES ECB":            ["crypto/aes_ecb/server.py"],
    "Template Programming": ["web/template_injection/site/app.py"],
}


def _login():
    s = requests.Session()
    page = s.get(f"{CTFD_URL}/login")
    import re
    nonce = re.search(r'name="nonce".*?value="([^"]+)"', page.text)
    if not nonce:
        nonce = re.search(r'nonce.*?value="([^"]+)"', page.text)
    s.post(f"{CTFD_URL}/login", data={
        "name": CTFD_USER, "password": CTFD_PASS,
        "nonce": nonce.group(1) if nonce else "",
    })
    return s


def get_challenges(s):
    r = s.get(f"{CTFD_URL}/api/v1/challenges?per_page=200")
    r.raise_for_status()
    return {c["name"]: c["id"] for c in r.json()["data"]}


def get_existing_files(s, challenge_id):
    r = s.get(f"{CTFD_URL}/api/v1/challenges/{challenge_id}/files")
    if not r.ok:
        return set()
    return {os.path.basename(f["location"]) for f in r.json().get("data", [])}


def upload_file(s, challenge_id, filepath):
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as fh:
        r = s.post(
            f"{CTFD_URL}/api/v1/files",
            data={"challenge_id": challenge_id, "type": "challenge"},
            files={"file": (filename, fh)},
        )
    r.raise_for_status()
    loc = r.json()["data"][0]["location"]
    print(f"  uploaded {filename} → {loc}")
    return loc


def main():
    s = _login()
    chals = get_challenges(s)
    print(f"Found {len(chals)} challenges in CTFd\n")

    for name, rel_paths in FILES.items():
        cid = chals.get(name)
        if not cid:
            print(f"[SKIP] '{name}' not found in CTFd")
            continue

        existing_names = get_existing_files(s, cid)

        print(f"[{name}] (id={cid})")
        for rel in rel_paths:
            filepath = os.path.normpath(os.path.join(CHALS_DIR, rel))
            fname = os.path.basename(filepath)
            if not os.path.exists(filepath):
                print(f"  MISSING: {filepath}")
                continue
            if fname in existing_names:
                print(f"  already uploaded: {fname}")
                continue
            upload_file(s, cid, filepath)

    print("\nDone.")


if __name__ == "__main__":
    main()
