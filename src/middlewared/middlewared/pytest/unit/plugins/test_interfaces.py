import pytest

from asynctest import Mock

from middlewared.service import ValidationErrors
from middlewared.plugins.network import InterfacesService
from middlewared.pytest.unit.middleware import Middleware


INTERFACES = [
    {
        'id': 'em0',
        'name': 'em0',
        'fake': False,
        'type': 'PHYSICAL',
        'aliases': [],
        'options': '',
        'ipv4_dhcp': False,
        'ipv6_auto': False,
        'state': {
            'cloned': False,
        },
    },
    {
        'id': 'em1',
        'name': 'em1',
        'fake': False,
        'type': 'PHYSICAL',
        'aliases': [],
        'options': '',
        'ipv4_dhcp': False,
        'ipv6_auto': False,
        'state': {
            'cloned': False,
        },
    },
]

INTERFACES_WITH_VLAN = INTERFACES + [
    {
        'id': 'vlan5',
        'name': 'vlan5',
        'fake': False,
        'type': 'VLAN',
        'aliases': [],
        'options': '',
        'ipv4_dhcp': False,
        'ipv6_auto': False,
        'state': {
            'cloned': True,
        },
        'vlan_tag': 5,
        'vlan_parent_interface': 'em0',
    },
]


INTERFACES_WITH_LAG = INTERFACES + [
    {
        'id': 'lagg0',
        'name': 'lagg0',
        'fake': False,
        'type': 'LINK_AGGREGATION',
        'aliases': [],
        'options': '',
        'ipv4_dhcp': False,
        'ipv6_auto': False,
        'state': {
            'cloned': True,
        },
        'lag_ports': ['em0'],
    },
]


@pytest.mark.asyncio
async def test__interfaces_service__create_lagg_invalid_ports():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'LINK_AGGREGATION',
            'lag_protocol': 'LACP',
            'lag_ports': ['em0', 'igb2'],
        })
    assert 'interface_create.lag_ports.1' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_lagg_invalid_ports_cloned():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES_WITH_VLAN)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'LINK_AGGREGATION',
            'lag_protocol': 'LACP',
            'lag_ports': ['em1', 'vlan5'],
        })
    assert 'interface_create.lag_ports.1' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_lagg_invalid_ports_used():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES_WITH_LAG)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'LINK_AGGREGATION',
            'lag_protocol': 'LACP',
            'lag_ports': ['em0'],
        })
    assert 'interface_create.lag_ports.0' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_lagg_invalid_name():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'LINK_AGGREGATION',
            'name': 'mylag11',
            'lag_protocol': 'LACP',
            'lag_ports': ['em0'],
        })
    assert 'interface_create.name' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_lagg():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)
    m['datastore.query'] = Mock(return_value=[])
    m['datastore.insert'] = Mock(return_value=5)

    await InterfacesService(m).create({
        'type': 'LINK_AGGREGATION',
        'lag_protocol': 'LACP',
        'lag_ports': ['em0', 'em1'],
    })


@pytest.mark.asyncio
async def test__interfaces_service__create_vlan_invalid_parent():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'VLAN',
            'name': 'myvlan1',
            'vlan_tag': 5,
            'vlan_parent_interface': 'igb2',
        })
    assert 'interface_create.vlan_parent_interface' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_vlan_invalid_parent_used():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES_WITH_LAG)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'VLAN',
            'vlan_tag': 5,
            'vlan_parent_interface': 'em0',
        })
    assert 'interface_create.vlan_parent_interface' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_vlan_invalid_name():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).create({
            'type': 'VLAN',
            'name': 'myvlan1',
            'vlan_tag': 5,
            'vlan_parent_interface': 'em0',
        })
    assert 'interface_create.name' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__create_vlan():

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=INTERFACES)
    m['datastore.query'] = Mock(return_value=[])
    m['datastore.insert'] = Mock(return_value=5)

    await InterfacesService(m).create({
        'type': 'VLAN',
        'vlan_tag': 5,
        'vlan_parent_interface': 'em0',
    })


@pytest.mark.asyncio
async def test__interfaces_service__update_two_dhcp():

    interfaces_with_one_dhcp = INTERFACES.copy()
    interfaces_with_one_dhcp[0]['ipv4_dhcp'] = True

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=interfaces_with_one_dhcp)

    update_interface = interfaces_with_one_dhcp[1]

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).update(
            update_interface['id'], {
                'ipv4_dhcp': True,
            },
        )
    assert 'interface_update.ipv4_dhcp' in ve.value


@pytest.mark.asyncio
async def test__interfaces_service__update_two_same_network():

    interfaces_one_network = INTERFACES.copy()
    interfaces_one_network[0]['aliases'] = [
        {'type': 'INET', 'address': '192.168.5.2', 'netmask': 24},
    ]

    m = Middleware()
    m['interfaces.query'] = Mock(return_value=interfaces_one_network)
    m['datastore.query'] = Mock(return_value=[])
    m['datastore.insert'] = Mock(return_value=5)

    update_interface = interfaces_one_network[1]

    with pytest.raises(ValidationErrors) as ve:
        await InterfacesService(m).update(
            update_interface['id'], {
                'aliases': ['192.168.5.3/24'],
            },
        )
    assert 'interface_update.aliases.0' in ve.value
