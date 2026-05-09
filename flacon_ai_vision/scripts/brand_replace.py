"""Script de remplacement d'anciennes mentions de marque.

Exécuter depuis la racine du dépôt:
    python scripts/brand_replace.py

Ce script modifie en place les fichiers texte pour remplacer:
  - Falcon AI Vision -> Falcon AI Vision
  - Falcon AI Vision Platform -> Falcon AI Vision Platform
  - etc.

Il ignore les dossiers venv, node_modules et .git.
"""

import os
import pathlib

REPLACEMENTS = [
    # Branding text replacements (user-visible/marketing strings)
    ("FALCON AI VISION", "FALCON AI VISION"),
    ("Falcon AI Vision", "Falcon AI Vision"),
    ("Falcon AI Vision", "Falcon AI Vision"),
    ("Falcon AI Vision", "Falcon AI Vision"),
    ("FALCON AI VISION", "FALCON AI VISION"),
    ("falcon-ai-vision", "falcon-ai-vision"),
    ("falcon-ai-vision", "falcon-ai-vision"),
    ("falcon-ai-vision-platform", "falcon-ai-vision-platform"),
    ("falcon-ai-vision-platform", "falcon-ai-vision-platform"),
    ("falcon-aivision", "falcon-aivision"),
    ("FalconAIVision", "FalconAIVision"),
]

TEXT_EXTS = {
    '.md', '.mdx', '.txt', '.py', '.sh', '.ps1', '.psm1', '.bat', '.yml', '.yaml',
    '.json', '.html', '.htm', '.css', '.js', '.ts', '.tsx', '.jsx', '.ini', '.cfg',
    '.conf', '.rst'
}


def is_text_file(path: pathlib.Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS


def main():
    root = pathlib.Path(__file__).resolve().parent.parent

    modified = []
    summary = {old: 0 for old, _ in REPLACEMENTS}

    for path in root.rglob('*'):
        if path.is_dir():
            # Skip envs and node_modules
            if any(p in path.parts for p in ('venv_ai', 'node_modules', '.git')):
                continue
            continue

        if not is_text_file(path):
            continue

        # Avoid huge binary-like files
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:
            try:
                text = path.read_text(encoding='latin-1')
            except Exception:
                continue

        new_text = text
        for old, new in REPLACEMENTS:
            if old in new_text:
                count = new_text.count(old)
                new_text = new_text.replace(old, new)
                summary[old] += count

        if new_text != text:
            path.write_text(new_text, encoding='utf-8')
            modified.append(path)

    print(f"Modified {len(modified)} files")
    for old, count in summary.items():
        if count:
            print(f"Replaced {count} occurrences of '{old}'")


if __name__ == '__main__':
    main()
