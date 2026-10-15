"""Explicit TCU assent stays scoped to the operator-owned process."""
from types import SimpleNamespace
import sys

import pytest

from ras_commander import RasTcu
from ras_commander import _tcu_gui as gui


def test_gui_terms_require_explicit_operator_assent():
    with pytest.raises(ValueError, match='operator_acceptance=True'):
        RasTcu.accept_gui_terms()
    with pytest.raises(ValueError, match='operator_acceptance=True'):
        RasTcu.accept_gui_terms(operator_acceptance=1)


def test_agree_selection_requires_unique_visible_enabled_control():
    row = dict(hwnd=1,text='&I Agree',visible=True,enabled=True)
    assert gui._select_agree_button([row]) == row
    for controls in [[],[dict(row,enabled=False)],[row,dict(row,hwnd=2)]]:
        with pytest.raises(RuntimeError,match='exactly one'):
            gui._select_agree_button(controls)


@pytest.mark.parametrize("keep_running", [False, True])
def test_gui_acceptance_never_clicks_foreign_matching_dialog(monkeypatch, keep_running):
    import itertools
    clicks=[]
    class Gone(Exception):
        pass
    class Process:
        pid=100
        terminated=False
        def create_time(self):return 10.0
        def exe(self):return r'C:\HEC\6.0\Ras.exe'
        def children(self,recursive):return []
        def terminate(self):self.terminated=True
        def wait(self,timeout):return 0
    process=Process()
    monkeypatch.setitem(sys.modules,'psutil',SimpleNamespace(Process=lambda pid:process,NoSuchProcess=Gone,TimeoutExpired=TimeoutError))
    class Ui:
        def __init__(self):
            self.api=SimpleNamespace(IsWindow=lambda hwnd:True,IsWindowVisible=lambda hwnd:hwnd!=11 or not clicks,IsWindowEnabled=lambda hwnd:True,GetMenu=lambda hwnd:1)
        def windows(self):return [10,13] if clicks else [10,11]
        def pid(self,hwnd):return 999 if hwnd==10 else 100
        def text(self,hwnd):
            assert hwnd!=10
            return 'HEC-RAS 6.0.0' if hwnd==13 else gui.TCU_DIALOG_TITLE
        def class_name(self,hwnd):return 'ThunderRT6FormDC'
        def controls(self,hwnd):
            assert hwnd==11
            return [dict(hwnd=12,text='I Agree',visible=True,enabled=True)]
        def click(self,hwnd):clicks.append(hwnd)
        def close(self,hwnd):process.closed=True
    ticks=itertools.count()
    monkeypatch.setattr(gui,'_WindowsUi',Ui)
    monkeypatch.setattr(gui.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(gui.time,'sleep',lambda _:None)
    result=gui.accept_owned_terms(SimpleNamespace(pid=100),r'C:\HEC\6.0\Ras.exe',20, keep_running=keep_running)
    assert result['dialog_closed'] is True
    assert clicks==[12]
    assert getattr(process, "closed", False) is (not keep_running)
    assert not process.terminated


def test_explicit_assent_selects_agree_not_refusal():
    refuse=dict(hwnd=1,text='I DO NOT agree with the above Terms and Conditions for Use',visible=True,enabled=True)
    agree=dict(refuse,hwnd=2,text='I agree to the above Terms and Conditions for Use')
    assert gui._select_agree_button([refuse,agree])['hwnd']==2


def test_gui_verification_is_bound_to_runtime_hash(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'profile'))
    exe=tmp_path/'Ras.exe';exe.write_bytes(b'original-runtime')
    assert RasTcu._has_gui_verification(exe) is False
    RasTcu._save_gui_verification(exe,dict(operator_acceptance=True,dialog_closed=True,gui_ready_verified=True,graceful_exit=True))
    assert RasTcu._has_gui_verification(exe) is True
    exe.write_bytes(b'replaced-runtime')
    assert RasTcu._has_gui_verification(exe) is False
    RasTcu._gui_verification_path(exe).write_text('[]')
    assert RasTcu._has_gui_verification(exe) is False


@pytest.mark.parametrize('verified',[False,True])
def test_legacy_wine_status_requires_gui_evidence(monkeypatch,verified):
    monkeypatch.setattr('os.name','nt')
    monkeypatch.setattr(RasTcu,'_resolve_exe',staticmethod(lambda *a,**k:r'C:\HEC\6.0\Ras.exe'))
    monkeypatch.setattr(RasTcu,'_node_has_acceptance_state',staticmethod(lambda *a:True))
    monkeypatch.setattr(RasTcu,'_requires_gui_evidence',staticmethod(lambda *a:True))
    monkeypatch.setattr(RasTcu,'_has_gui_verification',staticmethod(lambda *a:verified))
    monkeypatch.setitem(sys.modules,'winreg',SimpleNamespace(HKEY_CURRENT_USER=1))
    result=RasTcu.status(ras_version='6.0')
    assert result.accepted is (True if verified else None)
    if not verified:assert result.reason=='legacy-wine-gui-verification-required'


@pytest.mark.parametrize('enabled',[False,True])
def test_existing_profile_requires_enabled_stable_owned_main_window(monkeypatch,enabled):
    import itertools
    class Gone(Exception):pass
    class Process:
        pid=100
        def create_time(self):return 10.0
        def exe(self):return r'C:\HEC\6.0\Ras.exe'
        def children(self,recursive):return []
        def terminate(self):pass
        def wait(self,timeout):return 0
    process=Process()
    monkeypatch.setitem(sys.modules,'psutil',SimpleNamespace(Process=lambda pid:process,NoSuchProcess=Gone,TimeoutExpired=TimeoutError))
    class Ui:
        def __init__(self):
            self.api=SimpleNamespace(IsWindowVisible=lambda hwnd:True,IsWindowEnabled=lambda hwnd:enabled,GetMenu=lambda hwnd:1)
        def windows(self):return [11]
        def pid(self,hwnd):return 100
        def text(self,hwnd):return 'HEC-RAS 6.0.0'
        def class_name(self,hwnd):return 'ThunderRT6FormDC'
        def click(self,hwnd):pytest.fail('Existing accepted profile must not trigger a click')
        def close(self,hwnd):pass
    ticks=itertools.count()
    monkeypatch.setattr(gui,'_WindowsUi',Ui)
    monkeypatch.setattr(gui.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(gui.time,'sleep',lambda _:None)
    if enabled:
        receipt=gui.accept_owned_terms(SimpleNamespace(pid=100),r'C:\HEC\6.0\Ras.exe',20)
        assert receipt['already_accepted_profile'] is True
        assert receipt['clicked'] is False
    else:
        with pytest.raises(TimeoutError):
            gui.accept_owned_terms(SimpleNamespace(pid=100),r'C:\HEC\6.0\Ras.exe',20)


@pytest.mark.parametrize("operator_acceptance", [False, 1, "true"])
def test_running_terms_require_explicit_operator_assent(operator_acceptance):
    with pytest.raises(ValueError, match="operator_acceptance=True"):
        RasTcu.accept_running_terms(100, expected_create_time=10.0,
                                    operator_acceptance=operator_acceptance)


@pytest.mark.parametrize("identity", ["reused_pid", "changed_executable"])
def test_live_terms_identity_failure_never_constructs_ui(monkeypatch, identity):
    process = SimpleNamespace(pid=100, create_time=lambda:11.0 if identity=="reused_pid" else 10.0,
                              exe=lambda:r"C:\foreign\Ras.exe")
    monkeypatch.setitem(sys.modules,"psutil",SimpleNamespace(Process=lambda _:process))
    monkeypatch.setattr(gui,"_WindowsUi",lambda:pytest.fail("Identity failure must precede UI access"))
    with pytest.raises(RuntimeError, match="no UI actions"):
        gui.accept_owned_terms(process,r"C:\HEC\6.0\Ras.exe",10,
                               keep_running=True,expected_create_time=10.0)


def test_live_terms_timeout_leaves_caller_process_running(monkeypatch):
    import itertools
    process=SimpleNamespace(pid=100,create_time=lambda:10.0,exe=lambda:r"C:\HEC\6.0\Ras.exe",
                            children=lambda **_:[],terminate=lambda:pytest.fail("Caller owns cleanup"))
    monkeypatch.setitem(sys.modules,"psutil",SimpleNamespace(Process=lambda _:process,NoSuchProcess=ProcessLookupError))
    monkeypatch.setattr(gui,"_WindowsUi",lambda:SimpleNamespace(windows=lambda:[]))
    ticks=itertools.count()
    monkeypatch.setattr(gui.time,"monotonic",lambda:next(ticks))
    monkeypatch.setattr(gui.time,"sleep",lambda _:None)
    with pytest.raises(TimeoutError):
        gui.accept_owned_terms(process,r"C:\HEC\6.0\Ras.exe",3,
                               keep_running=True,expected_create_time=10.0)
