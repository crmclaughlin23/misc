# main.py
"""
    This module organizes both local and archived (drive) CPC files into subfolders
    and then cleans the main folder.
    This allows local and User CPC clients to more quickly open and navigate Reporting tab
"""
import datetime
import os
import re
import shutil
import threading
import time
from pathlib import Path

from shared_config.sqlserver import PROD_SERVER, PYRO_DATABASE
from shared_utils.sqlserver import get_engine, read_table

# Config
print_lock = threading.Lock()

LOCAL_SRC_1 = Path(r'C:\CPC Data')
LOCAL_SRC_2 = Path(r'C:\ASC Data')

DRIVE_DEST = Path(r'\\ut02sa7\ac\Data')

# Age (in days) of files to keep in folders before archiving
CUTOFF_493 = datetime.datetime(year=2017, month=1, day=1)
CUTOFF_DRIVE = datetime.datetime.now() - datetime.timedelta(days=30)
CUTOFF_LOCAL = datetime.datetime.now() - datetime.timedelta(days=365)
# Local files newer than this are left alone (not organized yet)
CUTOFF_LOCAL_ORGANIZE = datetime.datetime.now() - datetime.timedelta(days=30)

# To re-copy files from source, set COPY_FILES_FROM_SOURCE = True
COPY_FILES_FROM_SOURCE = False

# To organize the files on the source machines into year subfolders, leave this True
ORGANIZE_SOURCE_FILES = True

# To delete source-machine files older than CUTOFF_LOCAL, set CLEAN_SOURCE_FILES = True
# (only runs when ORGANIZE_SOURCE_FILES is also True; this deletes files on the source machines)
CLEAN_SOURCE_FILES = False

# Setup
DRIVE_DEST.mkdir(parents=True, exist_ok=True)

EQUIP_DATA_QUERY = """
    SELECT DISTINCT
        PC,
        PCID,
        Site,
        Equip,
        Alt_Name,
        DAT_Name
    FROM [Equipment PCs]
    WHERE Site != 'Dayton'
        AND Alt_Name != 'OV39'
        AND PC LIKE '%-A'
"""

prod_engine = get_engine(PROD_SERVER, PYRO_DATABASE)
equip_data_df = read_table(prod_engine, EQUIP_DATA_QUERY)

equip_data = [
    {
        'PC': row['PC'],
        'PCID': row['PCID'],
        'Site': row['Site'],
        'Equip': row['Equip'],
        'Alt_Name': row['Alt_Name'],
        'DAT_Name': row['DAT_Name'],
    }
    for _, row in equip_data_df.iterrows()
]


# Functions
def copy_file(source, filename, destination, write_buffer_seconds=300):
    source_file_path = source / filename.name
    dest_file_path = destination / filename.name

    source_mtime = source_file_path.stat().st_mtime
    age_seconds = time.time() - source_mtime

    if age_seconds < write_buffer_seconds:
        with print_lock:
            print(f'\tSkipping {filename.name}: last written {age_seconds:.0f}s ago. Likely still being written...')
        return

    if not dest_file_path.exists() or dest_file_path.stat().st_mtime < source_mtime:
        try:
            shutil.copy2(source_file_path, dest_file_path)
            with print_lock:
                print(f'\tCopying {filename.name}')
        except Exception as e:
            with print_lock:
                print(f'\tError copying {filename.name}: {e}')


def organize_drive_files(root_dir, equip_info):
    """Organize drive files by machine, site, year, and 493 test"""
    pattern = re.compile(r'\w+[-_](\d{4})\d{4}-\d{3}\.DAT')
    created_dirs = set()

    for equipment in equip_info:
        alt_equip = equipment['Alt_Name']
        site_name = equipment['Site']
        dat_name = equipment['DAT_Name']

        with print_lock:
            print(f'\nOrganizing files for {alt_equip}')

        for file_path in Path(root_dir).iterdir():
            if not file_path.is_file():  # Skip directories
                continue
            filename = file_path.name
            equip_part: str = re.split('[-_]', str(filename), maxsplit=1)[0]
            match = pattern.search(str(filename))

            if match:
                year = match.group(1)
                if equip_part == dat_name:
                    # print(f"Matching {filename} to {equip}, {alt_equip}, {site_name}")
                    new_dirs = [
                        Path.joinpath(root_dir, site_name),
                        Path.joinpath(root_dir, alt_equip),
                        Path.joinpath(root_dir, site_name, f'{site_name} {year}'),
                        Path.joinpath(root_dir, alt_equip, f'{alt_equip} {year}'),
                    ]

                    if '_HC' in filename or '_SAT' in filename or '_TUS' in filename:
                        dir_493 = Path.joinpath(root_dir, '493')
                        dir_493_year = Path.joinpath(root_dir, '493', f'493 {year}')
                        new_dirs.append(dir_493)
                        new_dirs.append(dir_493_year)

                    for dir_path in new_dirs:
                        if dir_path not in created_dirs:
                            parent_dir = dir_path.parent
                            if not parent_dir.exists():
                                parent_dir.mkdir(parents=True, exist_ok=True)
                            dir_path.mkdir(exist_ok=True)
                            created_dirs.add(dir_path)

                        dest_file_path = Path.joinpath(dir_path, filename)

                        if not Path.exists(dest_file_path):
                            with print_lock:
                                print(f'  Copying {filename} to {dest_file_path}')
                            shutil.copy2(
                                Path.joinpath(root_dir, filename), dest_file_path
                            )


def organize_source_files(root_dir, equip_info):
    """Organizes local CPC Data and/or ASC Data folders by year.

    Files newer than CUTOFF_LOCAL_ORGANIZE are left where they are.
    """
    for equipment in equip_info:
        alt_equip = equipment['Alt_Name']
        dat_name = equipment['DAT_Name']

        with print_lock:
            print(f'\nOrganizing files for {alt_equip}')

        for file_path in Path(root_dir).iterdir():
            if not file_path.is_file():
                continue

            filename = file_path.name
            equip_part = re.split('[-_]', filename, maxsplit=1)[0]
            if equip_part != dat_name:
                continue

            file_date = parse_file_date(filename)
            if file_date is None:
                with print_lock:
                    print(f'\tSkipping {filename}: no YYYYMMDD date pattern in filename')
                continue

            if file_date >= CUTOFF_LOCAL_ORGANIZE:
                continue  # too new to organize

            year = file_date.strftime('%Y')
            dest_dirs = [Path(root_dir) / f'{alt_equip} {year}']

            if '_HC' in filename or '_SAT' in filename or '_TUS' in filename:
                dest_dirs.append(Path(root_dir) / f'{alt_equip} 493')

            for dest_dir in dest_dirs:
                dest_dir.mkdir(parents=True, exist_ok=True)
                copy_file(Path(root_dir), file_path, dest_dir)


def parse_file_date(filename):
    """Parse 8-digit YYYYMMDD date from DAT filename.
    Returns None if th filename does not contain that pattern."""

    match = re.search(r'\d{8}', filename)
    if not match:
        return None
    try:
        return datetime.datetime.strptime(match.group(), '%Y%m%d')
    except ValueError:
        return None


def clean_folders(directory, cutoff_date):
    """Delete .DAT files from this folder if the file's date is before cutoff_date"""
    for filename in Path(directory).glob('*.DAT'):
        if filename.name == 'Target.DAT':
            continue

        file_date = parse_file_date(filename.name)
        if file_date is None:
            with print_lock:
                print(f'Skipping {filename.name}: no YYYYMMDD date pattern in filename')
            continue

        if file_date < cutoff_date:
            file_path = Path.joinpath(directory, filename.name)
            file_path.unlink()
            with print_lock:
                print(f'Deleted {file_path}')


def main():
    """
    This script organizes CPC DAT file folders on the local machine
    as well as archive folders located on a shared drive.

    The following occurs:
        1. Copy local files to the archive location (if COPY_FILES_FROM_SOURCE)
        2. Organize the local files (files < 30 days old are left alone)
        3. Clean the local files (if CLEAN_SOURCE_FILES)
        4. Organize the drive files
        5. Clean the drive files
    """
    # Copy from, and organize, the source machines
    source_folders = []
    if COPY_FILES_FROM_SOURCE or ORGANIZE_SOURCE_FILES:
        print('Processing the source machines...')
        for equipment in equip_data:
            pcid = equipment['PCID']
            pc = equipment['PC']

            with print_lock:
                print(f'  \nChecking {pcid} ({pc})')
            source = None

            if Path(rf'\\{pcid}\c\{LOCAL_SRC_1.name}').exists():
                source = Path(rf'\\{pcid}\c\{LOCAL_SRC_1.name}')
            elif Path(rf'\\{pcid}\c\{LOCAL_SRC_2.name}').exists():
                source = Path(rf'\\{pcid}\c\{LOCAL_SRC_2.name}')
            else:
                print(
                    f'    {pc} could not be reached. Confirm {pcid} is the correct PCID...'
                )

            if source:
                source_folders.append(source)

                if COPY_FILES_FROM_SOURCE:
                    for filename in source.iterdir():
                        if filename.suffix == '.DAT':
                            copy_file(source, filename, DRIVE_DEST)

                if ORGANIZE_SOURCE_FILES:
                    organize_source_files(source, [equipment])
    else:
        print('Skipping the source machines...')

    # Clean the source machines. This waits until every equipment on every
    # machine has been organized, so no file is deleted before it was copied
    # into its year folder.
    if CLEAN_SOURCE_FILES and ORGANIZE_SOURCE_FILES:
        print('Cleaning source machine folders...')
        for source in set(source_folders):
            clean_folders(directory=source, cutoff_date=CUTOFF_LOCAL)

    # Organize DAT files
    organize_drive_files(DRIVE_DEST, equip_data)

    # Copy Target.DAT to all subdirectories
    target_file = 'Target.DAT'
    src_file_path = DRIVE_DEST / target_file

    if not src_file_path.exists():
        with print_lock:
            print(f'The file {src_file_path} does not exist...')
    else:
        for root, dirs, _files in os.walk(DRIVE_DEST):
            for directory in dirs:
                dest_file_path = Path(root) / directory / target_file
                if not dest_file_path.exists():
                    try:
                        shutil.copy2(src_file_path, dest_file_path)
                        with print_lock:
                            print(f'Target.DAT copied to {dest_file_path}')
                    except Exception as e:
                        with print_lock:
                            print(f'Error copying Target.DAT to {dest_file_path}: {e}')

    print('Copying of Target.DAT completed!')

    # Clean up folders
    print('Cleaning folders...')
    for equipment in equip_data:
        clean_folders(directory=DRIVE_DEST, cutoff_date=CUTOFF_DRIVE)
        clean_folders(
            directory=DRIVE_DEST / equipment['Alt_Name'], cutoff_date=CUTOFF_DRIVE
        )
        clean_folders(
            directory=DRIVE_DEST / equipment['Site'], cutoff_date=CUTOFF_DRIVE
        )
        clean_folders(directory=DRIVE_DEST / '493', cutoff_date=CUTOFF_493)


if __name__ == '__main__':
    print('Script started...')
    main()
    print('Script completed!')
