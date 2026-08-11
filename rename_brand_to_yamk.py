#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ymk to Yamk Converter Script

This script renames files and directories containing Ymk/ymk variants to Yamk/yamk,
and replaces the same text variants inside text files.

Usage:
  Interactive mode:
    python rename_brand_to_yamk.py

  Command-line mode:
    python rename_brand_to_yamk.py <directory-path>
"""

import os
import sys
import argparse
import zipfile
from pathlib import Path

# Directories to skip. These are dependency/build/cache folders, not source files.
IGNORE_DIRS = {
    '.git', '.hg', '.svn',
    '.idea', '.vscode', '.vs',
    '.cache', '.output', '.next', '.nuxt', '.svelte-kit', '.angular',
    '.dart_tool', '.pub-cache',
    '.gradle', 'gradle-cache',
    'node_modules', 'bower_components',
    'build', 'dist', 'out', 'coverage', '.nyc_output',
    'bin', 'obj', 'target', 'packages', 'TestResults',
    'Pods', 'DerivedData',
    'logs', '__pycache__',
}

TEXT_FILE_EXTENSIONS = {
    # Flutter / Dart
    '.dart', '.arb',

    # Android / Kotlin / Java / Gradle
    '.kt', '.kts', '.java', '.gradle', '.properties', '.pro', '.aidl',

    # iOS / macOS / Windows native project files
    '.swift', '.m', '.mm', '.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp',
    '.rc', '.plist', '.entitlements', '.xcconfig', '.pbxproj', '.storyboard',
    '.xib', '.strings', '.xcworkspacedata', '.xcscheme', '.cmake',

    # Web apps
    '.html', '.htm', '.css', '.scss', '.sass', '.less', '.js', '.jsx', '.ts',
    '.tsx', '.mjs', '.cjs', '.vue', '.svelte', '.astro', '.mdx', '.map',
    '.webmanifest',

    # C# / .NET
    '.cs', '.csproj', '.fs', '.fsproj', '.vb', '.vbproj', '.sln', '.slnx',
    '.props', '.targets', '.config', '.resx', '.razor', '.cshtml', '.aspx',
    '.ascx', '.master', '.xaml', '.wxs', '.wxi', '.nuspec', '.runsettings',
    '.pubxml',

    # Common source/config/documentation files
    '.py', '.pyw', '.php', '.rb', '.go', '.rs', '.scala', '.sql',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.psm1', '.psd1', '.bat', '.cmd',
    '.json', '.jsonc', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.env', '.xml', '.svg', '.md', '.markdown', '.txt', '.text', '.csv',
    '.tsv', '.http', '.graphql', '.gql', '.proto', '.lock',
    '.editorconfig', '.dockerignore', '.gitignore', '.gitattributes',
    '.npmrc', '.nvmrc', '.prettierrc', '.eslintrc', '.stylelintrc',
}

BINARY_FILE_EXTENSIONS = {
    # Images / design assets
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp', '.tif', '.tiff',
    '.avif', '.psd', '.ai', '.sketch', '.fig',

    # Audio / video
    '.mp3', '.wav', '.ogg', '.m4a', '.flac', '.mp4', '.mov', '.avi', '.mkv',
    '.webm',

    # Fonts
    '.ttf', '.otf', '.woff', '.woff2', '.eot',

    # Archives / app packages
    '.zip', '.rar', '.7z', '.tar', '.gz', '.tgz', '.bz2', '.xz',
    '.jar', '.aar', '.war', '.nupkg', '.apk', '.aab', '.ipa', '.appx',
    '.msix', '.dmg', '.iso',

    # Native binaries / compiled artifacts
    '.exe', '.dll', '.pdb', '.so', '.dylib', '.a', '.lib', '.class', '.dex',
    '.wasm',

    # Databases / documents / secrets stores
    '.db', '.sqlite', '.sqlite3', '.mdb', '.pdf', '.doc', '.docx', '.xls',
    '.xlsx', '.ppt', '.pptx', '.p12', '.pfx', '.jks', '.keystore',
}

TEXT_FILE_NAMES = {
    'Dockerfile', 'Containerfile', 'Makefile', 'CMakeLists.txt',
    'Package.swift', 'Podfile', 'Gemfile', 'Fastfile', 'Appfile',
    'README', 'LICENSE', 'CHANGELOG', 'Changes',
    '.metadata', '.flutter-plugins', '.flutter-plugins-dependencies',
}

REPLACEMENTS = (
    ('vnrom', 'yamkrom'),
    ('vnROM', 'yamkROM'),
    ('VNROM', 'YAMKROM'),
)

SCRIPT_PATH = Path(__file__).resolve()
IGNORE_DIR_NAMES = {name.lower() for name in IGNORE_DIRS}
TEXT_FILE_NAMES_LOWER = {name.lower() for name in TEXT_FILE_NAMES}
READ_SAMPLE_SIZE = 8192
CONTROL_BYTES_ALLOWED_IN_TEXT = {9, 10, 12, 13}
FALLBACK_ENCODINGS = ('utf-8', 'utf-8-sig', 'cp1256', 'cp1252', 'latin-1')

def apply_replacements(value: str) -> str:
    result = value
    for old, new in REPLACEMENTS:
        result = result.replace(old, new)
    return result

def is_ignored_dir_name(name: str) -> bool:
    return name.lower() in IGNORE_DIR_NAMES

def has_known_text_name(name: str) -> bool:
    lower_name = name.lower()
    return (
        lower_name in TEXT_FILE_NAMES_LOWER
        or lower_name.startswith('.env')
        or 'dockerfile' in lower_name
    )

def looks_like_plain_text(sample: bytes) -> bool:
    if not sample:
        return True

    control_count = sum(
        1
        for byte in sample
        if byte < 32 and byte not in CONTROL_BYTES_ALLOWED_IN_TEXT
    )
    return control_count / len(sample) < 0.05

def likely_utf16_encoding(sample: bytes):
    if len(sample) < 4:
        return None

    even_bytes = sample[0::2]
    odd_bytes = sample[1::2]
    even_null_ratio = even_bytes.count(0) / len(even_bytes)
    odd_null_ratio = odd_bytes.count(0) / len(odd_bytes)

    if odd_null_ratio > 0.25 and even_null_ratio < 0.05:
        return 'utf-16-le'
    if even_null_ratio > 0.25 and odd_null_ratio < 0.05:
        return 'utf-16-be'
    return None

def detect_text_encoding_from_sample(name: str, sample: bytes, allow_binary_extension: bool = False):
    ext = Path(name).suffix.lower()

    if ext in BINARY_FILE_EXTENSIONS and not allow_binary_extension:
        return None

    if sample.startswith((b'\xff\xfe', b'\xfe\xff')):
        return 'utf-16'
    if sample.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'

    known_text_file = ext in TEXT_FILE_EXTENSIONS or has_known_text_name(name)

    if b'\x00' in sample:
        return likely_utf16_encoding(sample) if known_text_file else None

    if not known_text_file and not looks_like_plain_text(sample):
        return None

    for encoding in FALLBACK_ENCODINGS:
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue

    return None

def detect_text_encoding(file_path: Path):
    try:
        with open(file_path, 'rb') as file:
            sample = file.read(READ_SAMPLE_SIZE)
    except OSError:
        return None

    return detect_text_encoding_from_sample(file_path.name, sample)

def read_text_file(file_path: Path, encoding: str) -> str:
    with open(file_path, 'r', encoding=encoding, newline='') as file:
        return file.read()

def write_text_file(file_path: Path, content: str, encoding: str) -> None:
    with open(file_path, 'w', encoding=encoding, newline='') as file:
        file.write(content)

def make_replacement_zip_info(source_info: zipfile.ZipInfo, new_name: str) -> zipfile.ZipInfo:
    new_info = zipfile.ZipInfo(new_name, source_info.date_time)
    new_info.comment = source_info.comment
    new_info.extra = source_info.extra
    new_info.create_system = source_info.create_system
    new_info.create_version = source_info.create_version
    new_info.extract_version = source_info.extract_version
    new_info.flag_bits = source_info.flag_bits
    new_info.internal_attr = source_info.internal_attr
    new_info.external_attr = source_info.external_attr
    new_info.compress_type = source_info.compress_type
    return new_info

def replace_zip_entry_content(name: str, data: bytes):
    encoding = detect_text_encoding_from_sample(name, data[:READ_SAMPLE_SIZE])
    if not encoding:
        return data, False

    try:
        content = data.decode(encoding)
        new_content = apply_replacements(content)
        if new_content == content:
            return data, False
        return new_content.encode(encoding), True
    except UnicodeError:
        return data, False

def make_temp_zip_path(file_path: Path) -> Path:
    for index in range(1000):
        suffix = '.tmp' if index == 0 else f'.tmp{index}'
        candidate = file_path.with_name(file_path.name + suffix)
        if not candidate.exists():
            return candidate
    raise RuntimeError(f'Could not create temporary file name for {file_path}')

def process_zip_archive(file_path: Path):
    if file_path.suffix.lower() != '.zip' or not zipfile.is_zipfile(file_path):
        return None

    archive_modified = False
    entries_modified = 0
    entries_renamed = 0
    seen_names = set()
    temp_path = make_temp_zip_path(file_path)

    try:
        with zipfile.ZipFile(file_path, 'r') as source_zip:
            with zipfile.ZipFile(temp_path, 'w') as target_zip:
                for source_info in source_zip.infolist():
                    new_name = apply_replacements(source_info.filename)
                    if new_name in seen_names:
                        raise RuntimeError(f'Duplicate ZIP entry after rename: {new_name}')
                    seen_names.add(new_name)

                    if new_name != source_info.filename:
                        archive_modified = True
                        entries_renamed += 1

                    new_info = make_replacement_zip_info(source_info, new_name)

                    if source_info.is_dir():
                        target_zip.writestr(new_info, b'')
                        continue

                    data = source_zip.read(source_info)
                    new_data, content_modified = replace_zip_entry_content(new_name, data)
                    if content_modified:
                        archive_modified = True
                        entries_modified += 1

                    target_zip.writestr(new_info, new_data)

        if archive_modified:
            os.replace(temp_path, file_path)
        else:
            temp_path.unlink()

        return {
            'modified': archive_modified,
            'entries_modified': entries_modified,
            'entries_renamed': entries_renamed,
        }
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

def rename_and_replace(target_path: Path):
    full_path = target_path.resolve()
    
    if not full_path.exists():
        print(f'Error: Path "{full_path}" does not exist.')
        sys.exit(1)

    print(f"Starting conversion for: {full_path}\n")

    files_renamed = 0
    dirs_renamed = 0
    files_modified = 0
    files_skipped_binary = 0
    zip_archives_scanned = 0
    zip_archives_modified = 0
    zip_entries_modified = 0
    zip_entries_renamed = 0

    walk_items = []
    for root, dirs, files in os.walk(full_path, topdown=True):
        dirs[:] = [name for name in dirs if not is_ignored_dir_name(name)]
        walk_items.append((root, list(dirs), list(files)))

    # Process collected paths from leaves to root so directory renames happen last.
    for root, dirs, files in reversed(walk_items):
        # 1. Replace inside files & Rename files
        for name in files:
            file_path = Path(root) / name

            if file_path.is_symlink() or file_path.resolve() == SCRIPT_PATH:
                continue

            # Replace content
            zip_result = process_zip_archive(file_path)
            if zip_result is not None:
                zip_archives_scanned += 1
                zip_entries_modified += zip_result['entries_modified']
                zip_entries_renamed += zip_result['entries_renamed']
                if zip_result['modified']:
                    files_modified += 1
                    zip_archives_modified += 1
                    print(
                        f"Updated archive: {file_path} "
                        f"(entries content: {zip_result['entries_modified']}, "
                        f"entries renamed: {zip_result['entries_renamed']})"
                    )
            else:
                encoding = detect_text_encoding(file_path)
                if encoding:
                    try:
                        content = read_text_file(file_path, encoding)
                        new_content = apply_replacements(content)
                        if new_content != content:
                            write_text_file(file_path, new_content, encoding)
                            files_modified += 1
                            print(f"Updated content: {file_path}")
                    except UnicodeDecodeError:
                        files_skipped_binary += 1
                    except Exception as e:
                        print(f"Could not read/write {file_path}: {e}")
                else:
                    files_skipped_binary += 1

            # Rename file
            new_name = apply_replacements(name)
            if new_name != name:
                new_file_path = Path(root) / new_name
                try:
                    os.rename(file_path, new_file_path)
                    files_renamed += 1
                    print(f"Renamed file: {name} -> {new_name}")
                except Exception as e:
                    print(f"Could not rename {file_path}: {e}")

        # 2. Rename directories
        dir_name = os.path.basename(root)
        new_dir_name = apply_replacements(dir_name)
        if new_dir_name != dir_name and Path(root).resolve() != full_path:
            new_dir_path = os.path.join(os.path.dirname(root), new_dir_name)
            try:
                os.rename(root, new_dir_path)
                dirs_renamed += 1
                print(f"Renamed directory: {dir_name} -> {new_dir_name}")
            except Exception as e:
                print(f"Could not rename directory {root}: {e}")

    print("\nConversion complete.")
    print("Summary:")
    print(f"  - Files modified (content): {files_modified}")
    print(f"  - Files renamed: {files_renamed}")
    print(f"  - Directories renamed: {dirs_renamed}")
    print(f"  - Binary/non-text files skipped for content: {files_skipped_binary}")
    print(f"  - ZIP archives scanned: {zip_archives_scanned}")
    print(f"  - ZIP archives modified: {zip_archives_modified}")
    print(f"  - ZIP entries modified (content): {zip_entries_modified}")
    print(f"  - ZIP entries renamed: {zip_entries_renamed}")

def main():
    parser = argparse.ArgumentParser(description="Rename and replace Ymk/ymk variants with Yamk/yamk")
    parser.add_argument('path', nargs='?', help='Directory path to run the conversion. If not provided, runs interactive prompt.')
    args = parser.parse_args()

    if args.path:
        rename_and_replace(Path(args.path))
        return

    print('Ymk/ymk to Yamk/yamk Converter Script\n')
    try:
        input_path = input('Enter the full path to run the conversion: ').strip()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(1)

    if not input_path:
        print('Error: No path provided.')
        sys.exit(1)

    rename_and_replace(Path(input_path))

if __name__ == '__main__':
    main()
