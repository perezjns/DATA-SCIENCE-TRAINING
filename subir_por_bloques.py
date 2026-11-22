from pathlib import Path
import subprocess
import sys

REPO_DIR = Path.cwd()
MAX_BYTES = int(0.95 * 1024**3)  # ~0.95 GB por bloque para evitar HTTP 408


def run_git(args: list[str]) -> subprocess.CompletedProcess:
  print(f"\n> git {' '.join(args)}")
  return subprocess.run(["git", *args], cwd=REPO_DIR, text=True)


def get_size(path: Path) -> int:
  if path.is_file():
    return path.stat().st_size
  return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def get_pending_files() -> list[Path]:
  res = subprocess.run(
      ["git", "status", "--porcelain", "-uall"],
      cwd=REPO_DIR,
      capture_output=True,
      text=True,
  )
  files: list[Path] = []
  seen: set[Path] = set()

  for line in res.stdout.splitlines():
    if len(line) < 4:
      continue
    rel_path = line[3:].strip().strip('"')
    if " -> " in rel_path:
      rel_path = rel_path.split(" -> ", 1)[1].strip('"')
    full = (REPO_DIR / rel_path).resolve()
    if full.exists() and full.is_file() and full not in seen:
      seen.add(full)
      files.append(full)

  return files


def build_units(files: list[Path], split_large_chapters: bool) -> list[Path]:
  units: list[Path] = []
  seen: set[Path] = set()

  for f in files:
    rel = f.relative_to(REPO_DIR)
    parts = rel.parts

    # Si está dentro de VIDEOS DATACAMP y tiene carpeta de capítulo:
    # .../VIDEOS DATACAMP/CAPÍTULO X.../archivo.mp4
    if len(parts) >= 4 and parts[1] == "VIDEOS DATACAMP":
      chapter_dir = REPO_DIR / parts[0] / parts[1] / parts[2]
      if split_large_chapters and get_size(chapter_dir) > MAX_BYTES:
        target = f
      else:
        target = chapter_dir
    elif len(parts) >= 2 and parts[0] != ".git":
      # Agrupa archivos sueltos (como los PDFs de SQL FUNDAMENTALS DATACAMP)
      target = f if f.suffix.lower() in {".mp4", ".zip", ".mkv", ".avi"} else (REPO_DIR / parts[0])
    else:
      target = f

    if target not in seen:
      seen.add(target)
      units.append(target)

  return units


def push_batch(batch: list[Path], batch_num: int, first_push: bool) -> bool:
  rels = [str(p.relative_to(REPO_DIR)) for p in batch]
  res_add = run_git(["add", "--", *rels])
  if res_add.returncode != 0:
    return False

  msg = f"Auto batch {batch_num}: {', '.join(rels[:2])}"
  if len(rels) > 2:
    msg += f" (+{len(rels) - 2} more)"

  res_commit = run_git(["commit", "-m", msg])
  if res_commit.returncode != 0:
    return False

  push_args = (
      ["push", "-u", "origin", "main", "--force"]
      if first_push
      else ["push", "-u", "origin", "main"]
  )
  res_push = run_git(push_args)
  return res_push.returncode == 0


def main() -> None:
  first_push = "--force-first" in sys.argv
  split_large_chapters = "--split-chapters" in sys.argv

  gitattrs = REPO_DIR / ".gitattributes"
  if gitattrs.exists():
    status = subprocess.run(
        ["git", "status", "--porcelain", ".gitattributes"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
      if not push_batch([gitattrs], 0, first_push):
        print("\nError al subir .gitattributes.")
        return
      first_push = False

  batch_num = 1
  while True:
    pending_files = get_pending_files()
    if not pending_files:
      print("\n¡Todo lo pendiente se ha subido sin errores!")
      break

    units = build_units(pending_files, split_large_chapters=split_large_chapters)
    current_batch: list[Path] = []
    current_size = 0

    for unit in units:
      sz = get_size(unit)
      if sz > MAX_BYTES and not current_batch:
        current_batch.append(unit)
        current_size = sz
        break
      if current_size + sz > MAX_BYTES and current_batch:
        break
      current_batch.append(unit)
      current_size += sz

    print(f"\n=== Tanda {batch_num} (~{current_size / (1024**3):.2f} GB) ===")
    ok = push_batch(current_batch, batch_num, first_push)
    if not ok:
      print(
          f"\nFalló la tanda {batch_num}. "
          "Si fue un capítulo entero muy pesado, deshaz ese commit "
          "('git reset --soft HEAD~1' y 'git reset') y relanza con '--split-chapters'."
      )
      break

    first_push = False
    batch_num += 1


if __name__ == "__main__":
  main()