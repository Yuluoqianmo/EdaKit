"""Windows installer smoke test in a new disposable directory; never target real Cadence."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    setup = args.setup.resolve(strict=True)
    root = args.workspace.resolve()
    if root.exists():
        parser.error('workspace must not already exist')
    root.mkdir(parents=True)
    app = root / 'App'
    spb = root / 'Cadence/SPB_17.2'
    (spb / 'tools/capture/tclscripts').mkdir(parents=True)
    (spb / 'tools/bin').mkdir()
    (spb / 'tools/bin/ipc2581_out.exe').write_bytes(b'fixture; not executed')
    pcbenv = spb.parent / 'SPB_Data/pcbenv'
    pcbenv.mkdir(parents=True)
    (pcbenv / 'env').write_text('set user_setting = keep\n', encoding='utf-8')
    (pcbenv / 'allegro.ilinit').write_bytes(b'; user startup\r\n')
    env = os.environ.copy()
    for key, path in [('LOCALAPPDATA', root/'profile/local'),
                      ('APPDATA', root/'profile/roaming'), ('HOME', pcbenv.parent)]:
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    config = root / 'profile/local/edakit/config.json'
    config.parent.mkdir()
    config.write_text(json.dumps(dict(footprint_lib=str(root/'lib/Footprints'),
        step_lib=str(root/'lib/STEP'), symbol_lib=str(root/'lib/Symbols'),
        project_olb=str(root/'lib/Symbols/EdaKit.olb'), cadence_root=str(spb))), encoding='utf-8')

    def install(name, *extra):
        subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/CURRENTUSER', f'/DIR={app}', f'/LOG={root/name}', *extra],
            env=env, check=True, timeout=180)

    def uninstall(name):
        subprocess.run([str(app/'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
            '/NORESTART', f'/LOG={root/name}'], env=env, check=True, timeout=180)

    # Regression: InitializeWizard used to expand {app} before initialization
    # when CADENCEROOT was omitted. No plugin deployment in this phase.
    install('startup.log', '/DEPLOY=0')
    assert (app/'edakit.exe').is_file()
    assert not (app/'deployment.ini').exists()
    uninstall('startup-uninstall.log')
    install('install.log', f'/CADENCEROOT={spb}')
    entry = spb/'tools/capture/tclscripts/capAutoLoad/edakitInit.tcl'
    assert entry.is_file()
    assert str(app/'edakit.exe').replace('\\', '/') in (pcbenv/'edakit/ibom.il').read_text(encoding='ascii')
    custom = entry.parent/'edakit/user.txt'
    custom.write_text('preserve', encoding='utf-8')
    install('reinstall.log', f'/CADENCEROOT={spb}')
    assert (pcbenv/'allegro.ilinit').read_bytes().count(b'; >>> EdaKit iBOM begin') == 1
    assert (pcbenv/'env').read_text(encoding='utf-8').count('# >>> lcsc2cadence begin') == 1
    assert '已记录 exe 路径' in (app/'deployment.log').read_text(encoding='utf-8')
    uninstall('uninstall.log')
    assert not entry.exists()
    assert not (pcbenv/'edakit/ibom.il').exists()
    assert b'EdaKit iBOM begin' not in (pcbenv/'allegro.ilinit').read_bytes()
    assert b'; user startup' in (pcbenv/'allegro.ilinit').read_bytes()
    assert '# >>> lcsc2cadence begin' not in (pcbenv/'env').read_text(encoding='utf-8')
    assert custom.read_text(encoding='utf-8') == 'preserve'
    assert config.is_file()
    print('PASS: startup without CADENCEROOT; install; reinstall; uninstall; user data preserved')


if __name__ == '__main__':
    main()
