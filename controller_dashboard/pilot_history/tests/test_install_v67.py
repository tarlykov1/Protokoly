from pathlib import Path
import subprocess
import os
import shutil

root=Path(__file__).resolve().parents[1]


def test_install_rollback_and_sqlite_integrity(tmp_path):
    app=tmp_path/'app'; destination=app/'controller_dashboard_test'
    destination.mkdir(parents=True)
    (destination/'data').mkdir()
    data=(destination/'data'/'pilot.sqlite');data.write_bytes(b'unchanged-original-db')
    archive=(destination/'data'/'pilot_comment_snapshots.sqlite');archive.write_bytes(b'unchanged-snapshots')
    (destination/'comment_archive_v66.py').write_text('# already installed')
    files=('timeline_v6.py','timeline_v6.js','timeline_v6.css','timeline_v6.html')
    for f in files:(destination/f).write_text('previous test code')
    env={**os.environ,'APP_DIR':str(app)}
    installed=subprocess.run(['bash',str(root/'install.sh')],env=env,capture_output=True,text=True,check=True)
    stamp=installed.stdout.split('Backups stamp: ')[1].splitlines()[0]
    assert 'Installed v6.7' in installed.stdout
    assert (destination/'overview_v67.py').is_file()
    assert data.read_bytes()==b'unchanged-original-db'
    assert archive.read_bytes()==b'unchanged-snapshots'
    assert (destination/'timeline_v6.py').read_text()!='previous test code'
    reverted=subprocess.run(['bash',str(root/'rollback.sh'),stamp],env=env,capture_output=True,text=True,check=True)
    assert 'reverted' in reverted.stdout
    assert (destination/'timeline_v6.py').read_text()=='previous test code'
    assert not (destination/'overview_v67.py').exists()
    assert data.read_bytes()==b'unchanged-original-db'
    assert archive.read_bytes()==b'unchanged-snapshots'
