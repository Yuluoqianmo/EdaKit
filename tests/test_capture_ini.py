import codecs
from pathlib import Path
import subprocess
import shutil

import pytest

from edakit.install import capture_ini


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path/'home'))
    monkeypatch.setenv('APPDATA', str(tmp_path/'roaming'))


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_sync_keeps_other_sections_paths_comments_and_is_idempotent(newline):
    original = newline.join(['[Part Management]', 'Connect=preserve-exactly',
        '[Footprint Viewer Type]', 'Type=Allegro', '[Allegro Footprints]',
        '; user libraries', 'Dir0=D:/vendor', 'Dir4=D:/custom',
        '[Preferences]', 'Example=keep', ''])
    result = capture_ini.updated_text(original, 'D:/EdaKit/Libraries/Footprints')
    assert 'Dir1=D:/EdaKit/Libraries/Footprints' in result
    assert result.index('Dir1=') < result.index('Dir0=')
    assert 'Dir0=D:/vendor'+newline+'Dir4=D:/custom' in result
    assert '[Preferences]'+newline+'Example=keep' in result
    assert 'Connect=preserve-exactly'+newline in result
    assert capture_ini.updated_text(result, 'D:/EdaKit/Libraries/Footprints') == result
    changed = capture_ini.updated_text(result, 'E:/New PCB')
    assert 'D:/EdaKit/Libraries/Footprints' not in changed
    assert 'Dir1=E:/New PCB' in changed
    assert 'Dir4=D:/custom' in changed


def test_existing_case_slashes_and_sparse_directory_numbers_are_preserved():
    source = '[Allegro Footprints]\nDir2="d:\\Libraries\\PCB"\n[Other]\na=b\n'
    assert capture_ini.updated_text(source, 'D:/Libraries/pcb') == source


@pytest.mark.parametrize('source', ['', '[Allegro Footprints]', '[Preferences]\nKeep=1'])
def test_missing_section_or_final_newline_is_supported(source):
    result = capture_ini.updated_text(source, 'D:/PCB')
    assert 'Dir0=D:/PCB\n' in result
    assert capture_ini.updated_text(result, 'D:/PCB') == result


@pytest.mark.parametrize('encoding,bom', [('utf-8',b''),('utf-8',codecs.BOM_UTF8),
    ('utf-16-le',codecs.BOM_UTF16_LE),('utf-16-be',codecs.BOM_UTF16_BE),('gbk',b'')])
def test_write_preserves_encoding_and_creates_exact_backup(tmp_path, monkeypatch, encoding, bom):
    monkeypatch.setattr(capture_ini.locale, 'getpreferredencoding', lambda _: 'gbk')
    path=tmp_path/'Capture.ini'
    content='[Preferences]\r\nKeep=中文\r\n[Allegro Footprints]\r\nDir0=D:/vendor\r\n'
    original=bom+content.encode(encoding)
    path.write_bytes(original)
    assert capture_ini.configure('D:/新封装库',ini_path=path) == path
    expected=bom+capture_ini.updated_text(content,'D:/新封装库').encode(encoding)
    assert path.read_bytes() == expected
    assert path.with_name('Capture.ini.edakit-before-footprints.bak').read_bytes() == original
    capture_ini.configure('D:/新封装库',ini_path=path)
    assert path.read_bytes() == expected


def test_profile_marker_selects_actual_capture_ini_over_install_default(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'app'))
    root=tmp_path/'Cadence/SPB_17.2'
    default=root.parent/'SPB_Data/cdssetup/OrCAD_Capture/17.2.0/Capture.ini'
    default.parent.mkdir(parents=True);default.touch()
    assert capture_ini.find_ini(root) == default
    actual=tmp_path/'custom-capture.ini';actual.touch()
    marker=tmp_path/'app/edakit/capture_ini_path.txt'
    marker.write_text('path='+str(actual)+'\n',encoding='utf-8')
    assert capture_ini.find_ini(root) == actual
    assert capture_ini.configure('D:/PCB',cadence_root=root,dry_run=True) == actual
    assert actual.read_bytes() == b''
    assert default.read_bytes() == b''


def test_missing_profile_is_not_created_and_invalid_path_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'app'))
    assert capture_ini.configure('D:/PCB',cadence_root=tmp_path/'SPB_17.2') is None
    for path in ['', 'D:/PCB\nDir0=bad', 'D:/PCB\x00']:
        with pytest.raises(ValueError):capture_ini.updated_text('[Allegro Footprints]\n',path)


@pytest.mark.skipif(shutil.which('tclsh') is None, reason='Tcl is unavailable')
def test_plugin_records_actual_capture_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'app'))
    actual=tmp_path/'custom profile.ini';actual.touch()
    driver=tmp_path/'driver.tcl'
    driver.write_text('''proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
set ::profile [lindex $argv 1]
proc GetIniPath {} { return $::profile }
source [lindex $argv 0]
''',encoding='ascii')
    plugin=Path(__file__).parents[1]/'src/edakit/install/templates/edakit.tcl'
    process=subprocess.run([shutil.which('tclsh'),str(driver),str(plugin),str(actual)],capture_output=True,text=True)
    assert process.returncode == 0,process.stdout+process.stderr
    marker=tmp_path/'app/edakit/capture_ini_path.txt'
    assert marker.read_text(encoding='utf-8').strip() == 'path='+str(actual)
    assert capture_ini.find_ini() == actual
    assert plugin.read_bytes().isascii()
