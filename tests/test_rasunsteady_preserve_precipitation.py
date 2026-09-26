from pathlib import Path
import shutil
import pytest
from ras_commander import RasUnsteady


def setup_case(tmp_path, kind='Precipitation Hydrograph', area='Area'):
    g = tmp_path/'case.g01'
    g.write_text('BC Line Name=ND\nBC Line Storage Area=Area\n')
    u = tmp_path/'case.u01'
    precip = (f'Boundary Location=,,,,,{area},,\r\nInterval=1HOUR\r\n'
              f'{kind}=2\r\n    1.00    2.00\r\nDSS File=rain.dss\r\nDSS Path=/A/B/C/D/E/F/\r\nUse DSS=True\r\n').encode()
    u.write_bytes(b'Flow Title=Test\r\n'+precip+b'Boundary Location=,,,,,Area,,Old\r\nFriction Slope=.001\r\nPrecipitation Mode=Enable\r\n')
    return g,u,precip


def test_preserves_precipitation_bytes_and_global_trailer(tmp_path):
    g,u,p = setup_case(tmp_path)
    result = RasUnsteady.replace_2d_boundary_locations(u,g,[{'area_2d':'Area','bc_line':'ND'}],preserve_area_precipitation=True)
    assert p in u.read_bytes()
    assert b'Precipitation Mode=Enable\r\n' in u.read_bytes()
    assert result['preserved_precipitation_locations']==[{'area_2d':'Area','bc_line':''}]
    assert b',Old' not in u.read_bytes()


@pytest.mark.parametrize('kind,area',[('Stage Hydrograph','Area'),('Unknown','Area'),('Precipitation Hydrograph','Other')])
def test_rejects_unsupported_without_mutation(tmp_path,kind,area):
    g,u,_ = setup_case(tmp_path,kind,area)
    before=u.read_bytes()
    with pytest.raises(ValueError,match='unsupported area-wide'):
        RasUnsteady.replace_2d_boundary_locations(u,g,[{'area_2d':'Area','bc_line':'ND'}],preserve_area_precipitation=True)
    assert u.read_bytes()==before


def test_default_still_replaces_area_precipitation(tmp_path):
    g,u,p=setup_case(tmp_path)
    RasUnsteady.replace_2d_boundary_locations(u,g,[{'area_2d':'Area','bc_line':'ND'}])
    assert p not in u.read_bytes()


@pytest.mark.parametrize('mixed',[False,True])
def test_rejects_duplicate_or_mixed_precipitation_blocks(tmp_path,mixed):
    g,u,p=setup_case(tmp_path)
    raw=u.read_bytes()
    replacement=p+b'Stage Hydrograph=0\r\n' if mixed else p+p
    u.write_bytes(raw.replace(p,replacement))
    before=u.read_bytes()
    with pytest.raises(ValueError,match='unsupported area-wide'):
        RasUnsteady.replace_2d_boundary_locations(u,g,[{'area_2d':'Area','bc_line':'ND'}],preserve_area_precipitation=True)
    assert u.read_bytes()==before


def test_real_austin_preserves_exact_precip_block(tmp_path):
    root=Path(r'T:\FEMA eBFE\26-014 CWE\data_staging\austin_oyster_ebfe\organized\AustinOyster_12040205\RAS Model\AustinOyster\Input')
    if not (root/'AustinOyster.u01').exists():
        pytest.skip('Austin fixture unavailable')
    u=Path(shutil.copy2(root/'AustinOyster.u01',tmp_path/'case.u01'))
    g=tmp_path/'case.g01'
    g.write_text('BC Line Name=ND\nBC Line Storage Area=Perimeter 1\n')
    raw=u.read_bytes()
    pieces=raw.split(b'Boundary Location=')
    precipitation=[b'Boundary Location='+piece for piece in pieces[1:] if b'Precipitation Hydrograph=' in piece]
    assert len(precipitation)==1
    result=RasUnsteady.replace_2d_boundary_locations(u,g,[{'area_2d':'Perimeter 1','bc_line':'ND'}],preserve_area_precipitation=True)
    assert precipitation[0] in u.read_bytes()
    assert len(result['removed_locations'])==66
