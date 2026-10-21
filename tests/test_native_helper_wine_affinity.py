"""Wine masks can contain CPU indices outside its exposed ProcessorCount."""
import pytest
from ras_commander import _native_helper as helper


class AffinityApi:
    def __init__(self, mask=0x30, system=0xFF):
        self.mask,self.system=mask,system
        self.actions=[]
    def get(self):return self.mask,self.system
    def set(self,mask):
        self.actions.append(mask)
        self.mask=mask


def test_native_wine_high_cpu_mask_is_verified_and_restored(monkeypatch):
    api=AffinityApi()
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    monkeypatch.setattr(helper,'_is_wine_helper_runtime',lambda:True)
    monkeypatch.setattr(helper.platform,'system',lambda:'Windows')
    with helper._wine_helper_single_cpu_affinity():
        assert api.mask==0x10
    assert api.mask==0x30
    assert api.actions==[0x10,0x30]


def test_native_wine_affinity_restores_after_helper_failure(monkeypatch):
    api=AffinityApi()
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    with pytest.raises(ValueError,match='helper failed'):
        with helper._windows_wine_single_cpu_affinity():
            raise ValueError('helper failed')
    assert api.mask==0x30


@pytest.mark.parametrize('process_mask,system_mask',[(0,0xFF),(0x10,0),(0x100,0xFF)])
def test_native_wine_affinity_refuses_invalid_masks(monkeypatch,process_mask,system_mask):
    api=AffinityApi(process_mask,system_mask)
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    with pytest.raises(RuntimeError,match='valid nonempty'):
        with helper._windows_wine_single_cpu_affinity():pytest.fail('Must not launch helper')
    assert not api.actions


def test_native_wine_affinity_readback_mismatch_refuses_helper(monkeypatch):
    api=AffinityApi()
    def broken_set(mask):api.actions.append(mask)
    api.set=broken_set
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    with pytest.raises(RuntimeError,match='single-CPU affinity readback'):
        with helper._windows_wine_single_cpu_affinity():pytest.fail('Must not launch helper')
    assert api.actions==[0x10,0x30]


def test_native_wine_affinity_set_failure_restores_and_refuses_helper(monkeypatch):
    api=AffinityApi()
    def broken_set(mask):
        api.actions.append(mask)
        if mask==0x10:raise OSError('set failed')
        api.mask=mask
    api.set=broken_set
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    with pytest.raises(OSError,match='set failed'):
        with helper._windows_wine_single_cpu_affinity():pytest.fail('Must not launch helper')
    assert api.actions==[0x10,0x30]


def test_native_wine_affinity_restore_failure_is_audited(monkeypatch,caplog):
    api=AffinityApi()
    def broken_set(mask):
        if mask==0x30:raise OSError('restore failed')
        api.mask=mask
    api.set=broken_set
    monkeypatch.setattr(helper,'_WindowsAffinityApi',lambda:api)
    with helper._windows_wine_single_cpu_affinity():assert api.mask==0x10
    assert 'Could not restore' in caplog.text
