"""
Analyse et preparation de dataset musical pour l'entrainement LoRA ACE-Step 1.5.
Format attendu par ACE-Step :
  song.mp3 + song.lyrics.txt + song.json (bpm, keyscale, caption, timesignature, language)

Ce module :
  - Analyse chaque fichier audio (duree, format, SR, RMS)
  - Detecte les .lyrics.txt et .json associes
  - Verifie la conformite au format ACE-Step
  - Genere les .json manquants (avec placeholders a remplir)
  - Evalue la diversite du dataset (cles, BPM, genres estimes)
  - Donne une note globale + recommandations
"""
import os
import sys
import json
import math
import pathlib

AUDIO_EXT = {".mp3", ".wav", ".flac", ".ogg", ".opus"}
MIN_DURATION_S = 30    # ACE-Step veut des morceaux complets, pas des snippets
MAX_DURATION_S = 600   # 10 min max raisonnable


def _load_audio_meta(path):
    """Retourne (duree_s, sample_rate) sans charger tout le signal."""
    try:
        import soundfile as sf
        info = sf.info(path)
        return round(info.duration, 1), info.samplerate
    except Exception:
        pass
    try:
        import librosa
        dur = librosa.get_duration(filename=path)
        import soundfile as sf
        info = sf.info(path)
        return round(dur, 1), info.samplerate
    except Exception:
        pass
    # dernier recours : mutagen
    try:
        import mutagen
        audio = mutagen.File(path)
        if audio and hasattr(audio.info, "length"):
            sr = getattr(audio.info, "sample_rate", None)
            return round(audio.info.length, 1), sr
    except Exception:
        pass
    return None, None


def _rms_db(path):
    """RMS moyen du fichier (niveau sonore)."""
    try:
        import soundfile as sf
        import numpy as np
        data, _ = sf.read(path, always_2d=True)
        data = data.mean(axis=1)
        rms = max(1e-12, float(np.mean(data.astype("float32") ** 2)) ** 0.5)
        return round(20 * math.log10(rms), 1)
    except Exception:
        return None


def analyze_music_file(path):
    """Analyse un fichier audio et ses fichiers satellites (.lyrics.txt, .json)."""
    p = pathlib.Path(path)
    stem = p.stem
    folder = p.parent

    # fichiers satellites attendus par ACE-Step
    lyrics_path = folder / f"{stem}.lyrics.txt"
    json_path = folder / f"{stem}.json"
    caption_path = folder / f"{stem}.caption.txt"

    dur, sr = _load_audio_meta(path)
    rms = _rms_db(path) if dur else None

    # lit le JSON existant
    meta = {}
    if json_path.exists():
        try:
            meta = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    issues = []
    if dur is None:
        issues.append("Unreadable")
    else:
        if dur < MIN_DURATION_S:
            issues.append(f"Too short ({dur:.0f}s, min {MIN_DURATION_S}s)")
        if dur > MAX_DURATION_S:
            issues.append(f"Too long ({dur:.0f}s) — can cause OOM on 16 GB")
    if not lyrics_path.exists():
        issues.append("Missing lyrics (.lyrics.txt)")
    if not json_path.exists() and not caption_path.exists():
        issues.append("Missing annotations (.json / .caption.txt)")
    if meta and not meta.get("bpm"):
        issues.append("BPM missing from JSON")
    if meta and not meta.get("keyscale"):
        issues.append("Key (keyscale) missing from JSON")
    if rms is not None and rms < -30:
        issues.append(f"Low sound level ({rms} dB) — normalize")

    # note
    crit = [i for i in issues if "Unreadable" in i or "missing" in i.lower()]
    if crit:
        score = "F" if "Unreadable" in " ".join(crit) else "D"
    elif issues:
        score = "C" if len(issues) > 1 else "B"
    else:
        score = "A"

    return {
        "file": p.name,
        "path": str(p),
        "ext": p.suffix.lower(),
        "duration_s": dur,
        "sample_rate": sr,
        "rms_db": rms,
        "has_lyrics": lyrics_path.exists(),
        "has_json": json_path.exists(),
        "meta": meta,
        "issues": issues,
        "score": score,
    }


def generate_json_template(path, overwrite=False):
    """Cree un .json template ACE-Step pour le fichier audio si absent."""
    p = pathlib.Path(path)
    out = p.parent / f"{p.stem}.json"
    if out.exists() and not overwrite:
        return False, str(out)
    template = {
        "caption": f"FILL: musical style description for {p.stem}",
        "bpm": 0,
        "keyscale": "FILL: e.g. C Major or A Minor",
        "timesignature": "4",
        "language": "fr",
    }
    out.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, str(out)


def prepare_dataset(folder, generate_missing_json=True):
    """
    Pour chaque fichier audio sans .json, genere un template JSON.
    Retourne la liste des fichiers modifies.
    """
    generated = []
    for p in pathlib.Path(folder).rglob("*"):
        if p.suffix.lower() in AUDIO_EXT:
            json_p = p.parent / f"{p.stem}.json"
            if not json_p.exists() and generate_missing_json:
                ok, out = generate_json_template(str(p))
                if ok:
                    generated.append(out)
    return generated


def analyze_music_folder(folder, callback_progress=None, callback_result=None):
    """Analyse tous les fichiers audio d'un dossier."""
    files = sorted([
        f for f in pathlib.Path(folder).rglob("*")
        if f.suffix.lower() in AUDIO_EXT
    ])
    total = len(files)
    if total == 0:
        return {"total": 0, "files": []}

    results = []
    for i, f in enumerate(files):
        if callback_progress:
            callback_progress(i, total, f.name)
        r = analyze_music_file(str(f))
        results.append(r)
        if callback_result:
            callback_result(r)

    # --- diversite ---
    bpms = [r["meta"].get("bpm") for r in results if r["meta"].get("bpm")]
    keys = [r["meta"].get("keyscale") for r in results if r["meta"].get("keyscale")]
    durations = [r["duration_s"] for r in results if r["duration_s"]]
    total_dur = sum(durations)
    scores = [r["score"] for r in results]
    grade_counts = {g: scores.count(g) for g in "ABCDF"}

    missing_lyrics = sum(1 for r in results if not r["has_lyrics"])
    missing_json = sum(1 for r in results if not r["has_json"])

    from collections import Counter
    issues_all = [i for r in results for i in r["issues"]]

    summary = {
        "total": total,
        "total_duration_min": round(total_dur / 60, 1),
        "avg_duration_s": round(total_dur / total, 1) if total else 0,
        "grade_counts": grade_counts,
        "overall_score": _overall_score(grade_counts, total),
        "missing_lyrics": missing_lyrics,
        "missing_json": missing_json,
        "bpm_range": [min(bpms), max(bpms)] if bpms else None,
        "unique_keys": sorted(set(keys)),
        "key_diversity": len(set(keys)),
        "bpm_diversity": len(set(bpms)),
        "top_issues": _top_issues(issues_all),
        "ace_step_ready": missing_lyrics == 0 and grade_counts.get("F", 0) == 0,
        "recommendation": _music_recommendation(total, total_dur, missing_lyrics, missing_json, grade_counts),
        "files": results,
    }
    return summary


def _overall_score(gc, total):
    ok = gc.get("A", 0) + gc.get("B", 0)
    if gc.get("F", 0) > 0:
        return "D"
    if ok / max(total, 1) > 0.8:
        return "A"
    if ok / max(total, 1) > 0.6:
        return "B"
    return "C"


def _top_issues(issues):
    from collections import Counter
    c = Counter(issues)
    return [{"issue": k, "count": v} for k, v in c.most_common(5)]


def _music_recommendation(total, total_dur_s, missing_lyrics, missing_json, gc):
    msgs = []
    if total < 5:
        msgs.append(f"⚠️ Only {total} track(s) — ACE-Step recommends ≥10 (ideally 20-50 per style)")
    elif total < 10:
        msgs.append(f"💡 {total} track(s) — OK, 20+ will give a better LoRA")
    else:
        msgs.append(f"✅ {total} track(s)")
    if missing_lyrics > 0:
        msgs.append(f"⚠️ {missing_lyrics} file(s) without lyrics — create the .lyrics.txt (Whisper can transcribe)")
    if missing_json > 0:
        msgs.append(f"💡 {missing_json} without annotations — click 'Generate JSON' to create the templates")
    bad = gc.get("C", 0) + gc.get("D", 0) + gc.get("F", 0)
    if bad > 0:
        msgs.append(f"⚠️ {bad} file(s) with issues — fix before training")
    return " · ".join(msgs)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_music.py <folder>")
        sys.exit(1)
    summary = analyze_music_folder(
        sys.argv[1],
        callback_progress=lambda i, t, n: print(f"[{i+1}/{t}] {n}", file=sys.stderr)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
