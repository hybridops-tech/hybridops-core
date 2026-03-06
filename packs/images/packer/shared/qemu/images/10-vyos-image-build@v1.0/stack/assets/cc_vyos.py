# vi: ts=4 expandtab
#
#    Copyright (C) 2009-2010 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2019 Sentrium S.L.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Kim Hagen <kim@sentrium.io>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import ipaddress
from pathlib import Path
from subprocess import run
from uuid import uuid4
from cloudinit import log as logging
from cloudinit.ssh_util import AuthKeyLineParser
from cloudinit.distros import ug_util
from cloudinit.distros import ALL_DISTROS
from cloudinit.config.schema import MetaSchema, get_meta_doc
from cloudinit.settings import PER_INSTANCE
try:
    from cloudinit.sources import INSTANCE_JSON_FILE
except ImportError:
    INSTANCE_JSON_FILE = "instance-data.json"
from cloudinit.stages import Init
from cloudinit.util import load_file, load_json, get_hostname_fqdn, get_cfg_by_path
from cloudinit.sources.DataSourceOVF import get_properties as ovf_get_properties
try:
    from vyos.configtree import ConfigTree
except ImportError as err:
    print(f'The module cannot be imported: {err}')

# configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

frequency = PER_INSTANCE

MODULE_DESCRIPTION = "Apply VyOS-specific cloud-init configuration."
MODULE_EXAMPLES = [
    """#cloud-config
vyos_config_commands:
  - set interfaces ethernet eth0 address 'dhcp'
"""
]

meta: MetaSchema = {
    "id": "cc_vyos",
    "name": "VyOS",
    "title": "Apply VyOS cloud-init configuration",
    "description": MODULE_DESCRIPTION,
    "examples": MODULE_EXAMPLES,
    "distros": [ALL_DISTROS],
    "frequency": PER_INSTANCE,
    "activate_by_schema_keys": ["vyos_config_commands"],
}

__doc__ = get_meta_doc(meta)

# default values
DEFAULT_ETH_MTU = 1500


class VyosError(Exception):
    """Raised when the distro runs into an exception when setting vyos config.
    This may happen when the ssh pub key format is wrong.
    """
    pass


# configure user account with password
def set_pass_login(config, user, password):
    # check if a password string is a hash or a plaintext password
    # the regex from Cloud-init documentation, so we should trust it for this purpose
    encrypted_pass = re.match(r'\$(1|2a|2y|5|6)(\$.+){2}', password)
    if encrypted_pass:
        logger.debug("Configuring encrypted password for: {}".format(user))
        config.set(['system', 'login', 'user', user, 'authentication', 'encrypted-password'], value=password, replace=True)
    else:
        logger.debug("Configuring plaintext password password for: {}".format(user))
        config.set(['system', 'login', 'user', user, 'authentication', 'plaintext-password'], value=password, replace=True)

    config.set_tag(['system', 'login', 'user'])

    # Return True if credentials added
    return True


# configure user account with ssh key
def set_ssh_login(config, user, key_string):
    ssh_parser = AuthKeyLineParser()
    key_parsed = ssh_parser.parse(key_string)
    logger.debug("Parsed SSH public key: type: {}, base64: \"{}\", comment: {}, options: {}".format(key_parsed.keytype, key_parsed.base64, key_parsed.comment, key_parsed.options))

    if key_parsed.keytype not in ['ssh-dss', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ssh-ed25519', 'ecdsa-sha2-nistp521']:
        logger.error("Key type {} not supported.".format(key_parsed.keytype))
        return False

    if not key_parsed.base64:
        logger.error("Key base64 not defined, wrong ssh key format.")
        return False

    if not key_parsed.comment or not re.fullmatch(r'^[\w]+$', key_parsed.comment, re.ASCII):
        logger.info("Generating UUID for an SSH key because a comment is empty or unacceptable by CLI")
        key_parsed.comment = "cloud-init-{}".format(uuid4())

    # check if a key with the same comment already exists
    if config.exists(['system', 'login', 'user', user, 'authentication', 'public-keys', key_parsed.comment]):
        logger.debug("Generating UUID for an SSH key because a public key with comment {} already exists for user {}".format(key_parsed.comment, user))
        key_parsed.comment = "cloud-init-{}".format(uuid4())

    config.set(['system', 'login', 'user', user, 'authentication', 'public-keys', key_parsed.comment, 'key'], value=key_parsed.base64, replace=True)
    config.set(['system', 'login', 'user', user, 'authentication', 'public-keys', key_parsed.comment, 'type'], value=key_parsed.keytype, replace=True)
    if key_parsed.options:
        config.set(['system', 'login', 'user', user, 'authentication', 'public-keys', key_parsed.comment, 'options'], value=key_parsed.options, replace=True)
    config.set_tag(['system', 'login', 'user'])
    config.set_tag(['system', 'login', 'user', user, 'authentication', 'public-keys'])
    logger.debug("Configured SSH public key for user: {}".format(user))

    # Return True if credentials added
    return True


# filter hostname to be sure that it can be applied
# NOTE: here we cannot attempt to deny anything prohibited, as it is too late.
# Therefore, we need only pass what is allowed, cutting everything else
def hostname_filter(hostname):
    # fallback to default hostname if provided name is completely unusable
    resulted_hostname = 'vyos'
    # define regex for alloweed characters and resulted hostname
    regex_characters = re.compile(r'[a-z0-9.-]', re.IGNORECASE)
    regex_hostname = re.compile(r'[a-z0-9](([a-z0-9-]\.|[a-z0-9-])*[a-z0-9])?', re.IGNORECASE)
    # filter characters
    filtered_characters = ''.join(regex_characters.findall(hostname))
    # check that hostname start and end by allowed characters and cut unsupported ones, limit to 64 characters total
    filtered_hostname = regex_hostname.search(filtered_characters)
    if filtered_hostname:
        resulted_hostname = filtered_hostname.group()[:64]

    if hostname != resulted_hostname:
        logger.warning("Hostname/domain was filtered: {} -> {}".format(hostname, resulted_hostname))
    # return safe to apply host-name value
    return resulted_hostname


# configure system parameters from OVF template
def set_config_ovf(config, ovf_environment):
    logger.debug("Applying configuration from an OVF template")

    # Check for 'null' values and replace them by the 'None'
    # this make the rest of the code easier
    for (ovf_property_key, ovf_property_value) in ovf_environment.items():
        if ovf_property_value == 'null':
            ovf_environment[ovf_property_key] = None

    # get all variables required for configuration
    ip_address = ovf_environment['ip0']
    ip_mask = ovf_environment['netmask0']
    gateway = ovf_environment['gateway']
    dns_string = ovf_environment['DNS']
    ntp_string = ovf_environment['NTP']
    api_key = ovf_environment['APIKEY']
    api_port = ovf_environment['APIPORT']
    api_debug = ovf_environment['APIDEBUG']

    # Configure an interface and default route
    if ip_address and ip_mask and gateway:
        ip_address_cidr = ipaddress.ip_interface("{}/{}".format(ip_address, ip_mask.replace('/', ''))).with_prefixlen
        logger.debug("Configuring the IP address on the eth0 interface: {}".format(ip_address_cidr))
        set_ipaddress(config, 'ethernet', 'eth0', ip_address_cidr)

        logger.debug("Configuring default route via: {}".format(gateway))
        set_ip_route(config, 4, '0.0.0.0/0', gateway, True)
    else:
        logger.debug("Configuring a DHCP client on the eth0 interface (fallback from OVF)")
        set_ipaddress(config, 'ethernet', 'eth0', 'dhcp')

    # Configure DNS servers
    if dns_string:
        dns_list = list(dns_string.replace(' ', '').split(','))
        for server in dns_list:
            set_name_server(config, server)

    # Configure NTP servers
    if ntp_string:
        ntp_list = list(ntp_string.replace(' ', '').split(','))
        config.delete(['service', 'ntp'])
        for server in ntp_list:
            logger.debug("Configuring NTP server: {}".format(server))
            config.set(['service', 'ntp', 'server'], value=server, replace=False)
            config.set_tag(['service', 'ntp', 'server'])

    # Configure API
    if api_key:
        logger.debug("Configuring HTTP API key: {}".format(api_key))
        config.set(['service', 'https', 'api', 'keys', 'id', 'cloud-init', 'key'], value=api_key, replace=True)
        config.set_tag(['service', 'https', 'api', 'keys', 'id'])
    if api_key and api_port:
        logger.debug("Configuring HTTP API port: {}".format(api_port))
        config.set(['service', 'https', 'port'], value=api_port, replace=True)
    if api_key and api_debug != 'False':
        logger.debug("Enabling HTTP API debug")
        config.set(['service', 'https', 'api', 'debug'], replace=True)


# get an IP address type
def get_ip_type(address):
    addr_type = None
    if address in ['dhcp', 'dhcpv6']:
        addr_type = address
    else:
        try:
            ip_version = ipaddress.ip_interface(address).version
            if ip_version == 4:
                addr_type = 'ipv4'
            if ip_version == 6:
                addr_type = 'ipv6'
        except Exception as err:
            logger.error("Unable to detect IP address type: {}".format(err))
    logger.debug("IP address {} have type: {}".format(address, addr_type))
    return addr_type


# configure IP address for interface
def set_ipaddress(config, iface_type: str, iface: str, address: str,
                  vlan_id: int = 0):
    # detect an IP address type
    addr_type = get_ip_type(address)
    if not addr_type:
        logger.error("Unable to configure the IP address: {}".format(address))
        return
    # prepare for VLAN
    config_address_path = ['interfaces', iface_type, iface, 'address']
    if vlan_id:
        config_address_path = [
            'interfaces', iface_type, iface, 'vif', vlan_id, 'address'
        ]
    # check a current configuration of an interface
    if config.exists(config_address_path):
        current_addresses = config.return_values(config_address_path)
        logger.debug(
            "IP address for interface {} already configured: {}".format(
                iface, current_addresses))
        # check if currently configured addresses can be used with new one
        incompatible_addresses = []
        for current_address in current_addresses:
            # dhcp cannot be used with static IP address at the same time
            if ((addr_type == 'dhcp'
                 and get_ip_type(current_address) == 'ipv4')
                    or (addr_type == 'ipv4'
                        and get_ip_type(current_address) == 'dhcp')
                    or (addr_type == 'dhcpv6'
                        and get_ip_type(current_address) == 'ipv6')
                    or (addr_type == 'ipv6'
                        and get_ip_type(current_address) == 'dhcpv6')):
                incompatible_addresses.append(current_address)
        # inform about error and skip configuration
        if incompatible_addresses:
            logger.error(
                "IP address {} cannot be configured, because it conflicts with already exists: {}"
                .format(address, incompatible_addresses))
            return

    # configure address
    logger.debug("Configuring IP address {} on interface {}".format(
        address, iface))
    config.set(config_address_path, value=address, replace=False)
    config.set_tag(['interfaces', iface_type])
    if vlan_id:
        config.set_tag(['interfaces', iface_type, iface, 'vif'])


# configure MTU for Ethernet
def set_ether_mtu(config, iface: str, mtu: int) -> None:
    """Configure MTU for Ethernet interface

    Args:
        config (_type_): configuration object
        iface (str): interface name
        mtu (int): MTU value
    """
    logger.debug("Setting MTU for {}: {}".format(iface, mtu))
    # get maximum possible MTU
    iplink = run(['ip', '-json', '-detail', 'link', 'show', 'dev', iface],
                 capture_output=True)
    if iplink.returncode != 0:
        logger.debug("Cannot get interface details for {}".format(iface))
    else:
        iface_detail = load_json(iplink.stdout, root_types=(list,))
        if iface_detail:
            max_mtu = iface_detail[0].get('max_mtu')
            if max_mtu and max_mtu < mtu:
                logger.debug(
                    "Requested MTU ({}) is greater than maximum supported ({}), reducing it"
                    .format(mtu, max_mtu))
                mtu = max_mtu

    config.set(['interfaces', 'ethernet', iface, 'mtu'],
                value=mtu,
                replace=True)
    config.set_tag(['interfaces', 'ethernet'])


# configure IP route
def set_ip_route(config,
                 ip_ver: int,
                 dst_net: str,
                 next_hop: str,
                 replace_route: bool = False,
                 metric: int = 0) -> None:
    try:
        logger.debug(
            "Configuring IPv{} route to {} via {} with metric {}".format(
                ip_ver, dst_net, next_hop, metric))
        if ip_ver == 4:
            config.set(['protocols', 'static', 'route', dst_net, 'next-hop'],
                       value=next_hop,
                       replace=replace_route)
            config.set_tag(['protocols', 'static', 'route'])
            config.set_tag(
                ['protocols', 'static', 'route', dst_net, 'next-hop'])
            if metric:
                config.set([
                    'protocols', 'static', 'route', dst_net, 'next-hop',
                    next_hop, 'distance'
                ],
                           value=metric,
                           replace=True)
        if ip_ver == 6:
            config.set(['protocols', 'static', 'route6', dst_net, 'next-hop'],
                       value=next_hop,
                       replace=replace_route)
            config.set_tag(['protocols', 'static', 'route6'])
            config.set_tag(
                ['protocols', 'static', 'route6', dst_net, 'next-hop'])
            if metric:
                config.set([
                    'protocols', 'static', 'route6', dst_net, 'next-hop',
                    next_hop, 'distance'
                ],
                           value=metric,
                           replace=True)
    except Exception as err:
        logger.error("Impossible to configure an IP route: {}".format(err))


# configure DNS nameserver
def set_name_server(config, name_server: str) -> None:
    try:
        logger.debug("Configuring name-server {}".format(name_server))
        config.set(['system', 'name-server'], value=name_server, replace=False)
    except Exception as err:
        logger.error("Impossible to configure a name-server: {}".format(err))


# configure search domain
def set_domain_search(config, domain_search: str) -> None:
    try:
        logger.debug("Configuring DNS search domain: {}".format(domain_search))
        config.set(['system', 'domain-search'], value=domain_search, replace=False)
    except Exception as err:
        logger.error("Impossible to configure a name-server: {}".format(err))


# find usable interface name
def _find_usable_iface_name(config,
                            iface_type: str,
                            iface_prefix: str,
                            suggested_name: str = '') -> str:
    try:
        logger.debug(
            "Searching for usable interface name for type \"{}\", name prefix \"{}\", suggested name \"{}\""
            .format(iface_type, iface_prefix, suggested_name))
        # check if we can use a suggested name
        if suggested_name and iface_prefix == suggested_name.rstrip(
                '1234567890'):
            return suggested_name
        # return interface with zero index if no interfaces exists currently
        usable_iface_name = "{}{}".format(iface_prefix, '0')
        # check if already exists any interfaces with this type
        if config.exists(['interfaces', iface_type]):
            iface_names_current = config.list_nodes(['interfaces', iface_type])
            iface_found = False
            iface_number = int(0)
            while iface_found is False:
                usable_iface_name = "{}{}".format(iface_prefix, iface_number)
                if usable_iface_name not in iface_names_current:
                    iface_found = True
                else:
                    iface_number = iface_number + 1

        # return an interface name
        logger.debug("Suggested interface name: {}".format(usable_iface_name))
        return usable_iface_name
    except Exception as err:
        logger.error(
            "Impossible to find an usable interface name for type {}, name prefix {}: {}"
            .format(iface_type, iface_prefix, err))
        return ''


# configure subnets for an interface using networking config version 1
def _configure_subnets_v1(config,
                          iface_type: str,
                          iface_name: str,
                          subnets: list,
                          vlan_id: int = 0):
    for subnet in subnets:
        # configure DHCP client
        if subnet['type'] in ['dhcp', 'dhcp4', 'dhcp6']:
            if subnet['type'] == 'dhcp6':
                set_ipaddress(config, iface_type, iface_name, 'dhcpv6',
                              vlan_id)
            else:
                set_ipaddress(config, iface_type, iface_name, 'dhcp', vlan_id)
            continue

        # configure static options
        if subnet['type'] in ['static', 'static6']:
            # configure IP address
            try:
                ip_interface = ipaddress.ip_interface(subnet['address'])
                ip_version = ip_interface.version
                ip_address = ip_interface.ip.compressed
                ip_static_addr = ''
                # format IPv4
                if ip_version == 4 and ip_address != '0.0.0.0':
                    if '/' in subnet['address']:
                        ip_static_addr = ip_interface.compressed
                    else:
                        ip_static_addr = ipaddress.IPv4Interface(
                            '{}/{}'.format(ip_address,
                                           subnet['netmask'])).compressed
                # format IPv6
                if ip_version == 6:
                    ip_static_addr = ip_interface.compressed
                # apply to the configuration
                if ip_static_addr:
                    set_ipaddress(config, iface_type, iface_name,
                                  ip_static_addr, vlan_id)
            except Exception as err:
                logger.error(
                    "Impossible to configure static IP address: {}".format(
                        err))

            # configure gateway
            if 'gateway' in subnet and subnet['gateway'] != '0.0.0.0':
                logger.debug("Configuring gateway for {}: {}".format(
                    iface_name, subnet['gateway']))
                set_ip_route(config, 4, '0.0.0.0/0', subnet['gateway'], True)

            # configure routes
            if 'routes' in subnet:
                for item in subnet['routes']:
                    ip_network = ipaddress.ip_network('{}/{}'.format(
                        item['network'], item['netmask']))
                    set_ip_route(config, ip_network.version,
                                 ip_network.compressed, item['gateway'], True)

            # configure nameservers
            if 'dns_nameservers' in subnet:
                for item in subnet['dns_nameservers']:
                    set_name_server(config, item)

            if 'dns_search' in subnet:
                for item in subnet['dns_search']:
                    set_domain_search(config, item)


# configure interface from networking config version 1
def set_config_interfaces_v1(config, iface_config: dict):
    logger.debug("Configuring network using Cloud-init networking config version 1")
    # configure physical interfaces
    if iface_config['type'] == 'physical':
        iface_name = iface_config['name']

        # configre MAC
        if 'mac_address' in iface_config:
            logger.debug("Setting MAC for {}: {}".format(iface_name, iface_config['mac_address']))
            config.set(['interfaces', 'ethernet', iface_name, 'hw-id'], value=iface_config['mac_address'], replace=True)
            config.set_tag(['interfaces', 'ethernet'])

        # configre MTU
        if 'mtu' in iface_config and iface_config['mtu'] is not None:
            set_ether_mtu(config, iface_name, iface_config['mtu'])
        # We still need to set default MTU for Ethernet, for compatibility reasons
        else:
            set_ether_mtu(config, iface_name, DEFAULT_ETH_MTU)


        # configure subnets
        if 'subnets' in iface_config:
            _configure_subnets_v1(config, 'ethernet', iface_name, iface_config['subnets'])

    # configure nameservers
    if iface_config['type'] == 'nameserver':
        # convert a string to list with a single item if necessary
        if isinstance(iface_config['address'], str):
            iface_config['address'] = [iface_config['address']]

        for item in iface_config['address']:
            set_name_server(config, item)

        for item in iface_config.get('search', []):
            set_domain_search(config, item)

    # configure routes
    if iface_config['type'] == 'route':
        ip_network = ipaddress.ip_network(iface_config['destination'])
        set_ip_route(config, ip_network.version, ip_network.compressed,
                     iface_config['gateway'], True, iface_config.get('metric', 0))

    # configure bonding interfaces
    if iface_config['type'] == 'bond':
        try:
            # find a next unused bonding interface name
            iface_name_suggested = iface_config.get('name', '')
            iface_name = _find_usable_iface_name(config, 'bonding', 'bond',
                                                 iface_name_suggested)
            # add an interface
            config.set(['interfaces', 'bonding', iface_name])
            config.set_tag(['interfaces', 'bonding'])
            # configure members
            for member in iface_config.get('bond_interfaces', []):
                config.set([
                    'interfaces', 'bonding', iface_name, 'member', 'interface'
                ],
                           value=member,
                           replace=False)
            # read bonding parameters that VyOS supports
            mac_address = iface_config.get('mac_address')
            mtu = iface_config.get('mtu')
            arp_interval = get_cfg_by_path(iface_config, 'params/arp_interval')
            arp_ip_target = get_cfg_by_path(iface_config,
                                            'params/arp_ip_target')
            lacp_rate = get_cfg_by_path(iface_config, 'params/lacp_rate')
            min_links = get_cfg_by_path(iface_config, 'params/min_links')
            mode = get_cfg_by_path(iface_config, 'params/mode')
            primary = get_cfg_by_path(iface_config, 'params/primary')
            xmit_hash_policy = get_cfg_by_path(iface_config,
                                               'params/xmit_hash_policy')
            # apply parameters
            if mac_address:
                config.set(['interfaces', 'bonding', iface_name, 'mac'],
                           value=mac_address,
                           replace=True)
            if mtu:
                config.set(['interfaces', 'bonding', iface_name, 'mtu'],
                           value=mtu,
                           replace=True)
            if arp_interval:
                config.set([
                    'interfaces', 'bonding', iface_name, 'arp-monitor',
                    'interval'
                ],
                           value=arp_interval,
                           replace=True)
            if arp_ip_target:
                ip_targets = arp_ip_target.split(',')
                for ip_target in ip_targets:
                    config.set([
                        'interfaces', 'bonding', iface_name, 'arp-monitor',
                        'target'
                    ],
                               value=ip_target,
                               replace=False)
            if lacp_rate:
                lacp_rate_translate = {
                    0: 'slow',
                    1: 'fast',
                    'slow': 'slow',
                    'fast': 'fast'
                }
                config.set(['interfaces', 'bonding', iface_name, 'lacp-rate'],
                           value=lacp_rate_translate[lacp_rate],
                           replace=True)
            if min_links:
                config.set(['interfaces', 'bonding', iface_name, 'min-links'],
                           value=min_links,
                           replace=True)
            if mode:
                mode_translate = {
                    0: 'round-robin',
                    1: 'active-backup',
                    2: 'xor-hash',
                    3: 'broadcast',
                    4: '802.3ad',
                    5: 'transmit-load-balance',
                    6: 'adaptive-load-balance',
                    'balance-rr': 'round-robin',
                    'active-backup': 'active-backup',
                    'balance-xor': 'xor-hash',
                    'broadcast': 'broadcast',
                    '802.3ad': '802.3ad',
                    'balance-tlb': 'transmit-load-balance',
                    'balance-alb': 'adaptive-load-balance'
                }
                config.set(['interfaces', 'bonding', iface_name, 'mode'],
                           value=mode_translate[mode],
                           replace=True)
            if primary:
                config.set(['interfaces', 'bonding', iface_name, 'primary'],
                           value=primary,
                           replace=True)
            if xmit_hash_policy:
                config.set(
                    ['interfaces', 'bonding', iface_name, 'hash-policy'],
                    value=xmit_hash_policy,
                    replace=True)

            # configure subnets
            if 'subnets' in iface_config:
                _configure_subnets_v1(config, 'bonding', iface_name,
                                      iface_config['subnets'])

        except Exception as err:
            logger.error(
                "Impossible to configure bonding interface: {}".format(err))

    # configure bridge interfaces
    if iface_config['type'] == 'bridge':
        try:
            # find a next unused bridge interface name
            iface_name_suggested = iface_config.get('name', '')
            iface_name = _find_usable_iface_name(config, 'bridge', 'br',
                                                 iface_name_suggested)
            # add an interface
            config.set(['interfaces', 'bridge', iface_name])
            config.set_tag(['interfaces', 'bridge'])
            # configure members
            for member in iface_config.get('bridge_interfaces', []):
                config.set([
                    'interfaces', 'bridge', iface_name, 'member', 'interface',
                    member
                ],
                           value=None,
                           replace=False)
                config.set_tag([
                    'interfaces', 'bridge', iface_name, 'member', 'interface'
                ])
            # read bridge parameters that VyOS supports
            bridge_ageing = get_cfg_by_path(iface_config,
                                            'params/bridge_ageing')
            bridge_bridgeprio = get_cfg_by_path(iface_config,
                                                'params/bridge_bridgeprio')
            bridge_fd = get_cfg_by_path(iface_config, 'params/bridge_fd')
            bridge_hello = get_cfg_by_path(iface_config, 'params/bridge_hello')
            bridge_hw = get_cfg_by_path(iface_config, 'params/bridge_hw')
            bridge_maxage = get_cfg_by_path(iface_config,
                                            'params/bridge_maxage')
            bridge_pathcost = get_cfg_by_path(iface_config,
                                              'params/bridge_pathcost')
            bridge_portprio = get_cfg_by_path(iface_config,
                                              'params/bridge_portprio')
            bridge_stp = get_cfg_by_path(iface_config, 'params/bridge_stp')
            # apply parameters
            if bridge_ageing:
                config.set(['interfaces', 'bridge', iface_name, 'aging'],
                           value=bridge_ageing,
                           replace=True)
            if bridge_bridgeprio:
                config.set(['interfaces', 'bridge', iface_name, 'priority'],
                           value=bridge_bridgeprio,
                           replace=True)
            if bridge_fd:
                config.set(
                    ['interfaces', 'bridge', iface_name, 'forwarding-delay'],
                    value=bridge_fd,
                    replace=True)
            if bridge_hello:
                config.set(['interfaces', 'bridge', iface_name, 'hello-time'],
                           value=bridge_hello,
                           replace=False)
            if bridge_hw:
                config.set(['interfaces', 'bridge', iface_name, 'mac'],
                           value=bridge_hw,
                           replace=True)
            if bridge_maxage:
                config.set(['interfaces', 'bridge', iface_name, 'max-age'],
                           value=bridge_maxage,
                           replace=True)
            if bridge_pathcost:
                for member_item in bridge_pathcost:
                    member_name, member_cost = member_item.split()
                    config.set([
                        'interfaces', 'bridge', iface_name, 'member',
                        'interface', member_name, 'cost'
                    ],
                               value=member_cost,
                               replace=True)
            if bridge_portprio:
                for member_item in bridge_portprio:
                    member_name, member_prio = member_item.split()
                    config.set([
                        'interfaces', 'bridge', iface_name, 'member',
                        'interface', member_name, 'priority'
                    ],
                               value=member_prio,
                               replace=True)
            if bridge_stp and bridge_stp == 'on':
                config.set(['interfaces', 'bridge', iface_name, 'stp'],
                           value=None,
                           replace=True)

            # configure subnets
            if 'subnets' in iface_config:
                _configure_subnets_v1(config, 'bridge', iface_name,
                                      iface_config['subnets'])

        except Exception as err:
            logger.error(
                "Impossible to configure bridge interface: {}".format(err))

    # configure vlan interfaces
    if iface_config['type'] == 'vlan':
        try:
            # get mandatory interface parameters
            iface_name = iface_config['name']
            vlan_link = iface_config['vlan_link']
            vlan_id = iface_config['vlan_id']
            # get optional parameters
            vlan_mtu = iface_config.get('mtu')
            # prepare translation table for parent interface type
            interface_type_detect = {
                'eth': 'ethernet',
                'br': 'bridge',
                'bond': 'bonding'
            }
            # find interface type
            iface_type = interface_type_detect[vlan_link.rstrip('1234567890')]
            # create an interface
            config.set(['interfaces', iface_type, vlan_link, 'vif', vlan_id])
            config.set_tag(['interfaces', iface_type])
            config.set_tag(['interfaces', iface_type, vlan_link, 'vif'])
            # configure optional parameters
            if vlan_mtu:
                config.set([
                    'interfaces', iface_type, vlan_link, 'vif', vlan_id, 'mtu'
                ],
                           value=vlan_mtu,
                           replace=True)
            # configure subnets
            if 'subnets' in iface_config:
                _configure_subnets_v1(config, iface_type, vlan_link,
                                      iface_config['subnets'], vlan_id)

        except Exception as err:
            logger.error(
                "Impossible to configure VLAN interface: {}".format(err))


# configure common interface options from Network-Config version 2
def config_net_v2_common(config,
                         iface_type: str,
                         iface_name: str,
                         iface_config: dict,
                         vlan_id: int = 0) -> None:
    # configure DHCP client
    if iface_config.get('dhcp4') is True:
        set_ipaddress(config, iface_type, iface_name, 'dhcp', vlan_id)
    if iface_config.get('dhcp6') is True:
        set_ipaddress(config, iface_type, iface_name, 'dhcpv6', vlan_id)

    # configure static addresses
    for item in iface_config.get('addresses', []):
        set_ipaddress(config, iface_type, iface_name, item, vlan_id)

    # configure gateways
    if 'gateway4' in iface_config:
        logger.debug("Configuring IPv4 gateway for {} (VLAN {}): {}".format(
            iface_name, vlan_id, iface_config['gateway4']))
        set_ip_route(config, 4, '0.0.0.0/0', iface_config['gateway4'], True)
    if 'gateway6' in iface_config:
        logger.debug("Configuring IPv6 gateway for {} (VLAN {}): {}".format(
            iface_name, vlan_id, iface_config['gateway6']))
        set_ip_route(config, 6, '::/0', iface_config['gateway6'], True)

    # configure MTU
    if 'mtu' in iface_config:
        logger.debug("Setting MTU for {} (VLAN {}): {}".format(
            iface_name, vlan_id, iface_config['mtu']))
        if vlan_id:
            config.set(
                ['interfaces', iface_type, iface_name, 'vif', vlan_id, 'mtu'],
                value=iface_config['mtu'],
                replace=True)
        else:
            if iface_type == 'ethernet':
                set_ether_mtu(config, iface_name, iface_config['mtu'])
            else:
                config.set(['interfaces', iface_type, iface_name, 'mtu'],
                           value=iface_config['mtu'],
                           replace=True)
        config.set_tag(['interfaces', iface_type])
    # We still need to set default MTU for Ethernet, for compatibility reasons
    elif 'mtu' not in iface_config and iface_type == 'ethernet':
        set_ether_mtu(config, iface_name, DEFAULT_ETH_MTU)

    # configure nameservers
    if 'nameservers' in iface_config:
        for item in iface_config['nameservers'].get('search', []):
            set_domain_search(config, item)
        for item in iface_config['nameservers'].get('addresses', []):
            set_name_server(config, item)

    # configure routes
    for item in iface_config.get('routes', []):
        set_ip_route(config,
                     ipaddress.ip_network(item['to']).version, item['to'],
                     item['via'], True, item.get('metric'))


# configure bond interafce from Network-Config version 2
def config_net_v2_bond(config, iface_name: str, iface_config: dict) -> None:
    # find an usable bonding interface name
    iface_name = _find_usable_iface_name(config, 'bonding', 'bond', iface_name)
    config_net_v2_common(config, 'bonding', iface_name, iface_config)
    # add an interface
    config.set(['interfaces', 'bonding', iface_name])
    config.set_tag(['interfaces', 'bonding'])
    # configure members
    for member in iface_config.get('interfaces', []):
        config.set(
            ['interfaces', 'bonding', iface_name, 'member', 'interface'],
            value=member,
            replace=False)
    # read bonding parameters that VyOS supports
    mode = get_cfg_by_path(iface_config, 'parameters/mode')
    lacp_rate = get_cfg_by_path(iface_config, 'parameters/lacp-rate')
    min_links = get_cfg_by_path(iface_config, 'parameters/min-links')
    transmit_hash_policy = get_cfg_by_path(iface_config,
                                           'parameters/transmit-hash-policy')
    arp_interval = get_cfg_by_path(iface_config, 'parameters/arp-interval')
    arp_ip_targets = get_cfg_by_path(iface_config, 'parameters/arp-ip-targets')
    # apply parameters
    if mode:
        mode_translate = {
            0: 'round-robin',
            1: 'active-backup',
            2: 'xor-hash',
            3: 'broadcast',
            4: '802.3ad',
            5: 'transmit-load-balance',
            6: 'adaptive-load-balance',
            'balance-rr': 'round-robin',
            'active-backup': 'active-backup',
            'balance-xor': 'xor-hash',
            'broadcast': 'broadcast',
            '802.3ad': '802.3ad',
            'balance-tlb': 'transmit-load-balance',
            'balance-alb': 'adaptive-load-balance'
        }
        config.set(['interfaces', 'bonding', iface_name, 'mode'],
                   value=mode_translate[mode],
                   replace=True)
    if lacp_rate:
        lacp_rate_translate = {
            0: 'slow',
            1: 'fast',
            'slow': 'slow',
            'fast': 'fast'
        }
        config.set(['interfaces', 'bonding', iface_name, 'lacp-rate'],
                   value=lacp_rate_translate[lacp_rate],
                   replace=True)
    if min_links:
        config.set(['interfaces', 'bonding', iface_name, 'min-links'],
                   value=min_links,
                   replace=True)
    if transmit_hash_policy:
        config.set(['interfaces', 'bonding', iface_name, 'hash-policy'],
                   value=transmit_hash_policy,
                   replace=True)
    if arp_interval:
        config.set(
            ['interfaces', 'bonding', iface_name, 'arp-monitor', 'interval'],
            value=arp_interval,
            replace=True)
    # TODO: check the exact format of this option
    if arp_ip_targets:
        for ip_target in arp_ip_targets:
            config.set(
                ['interfaces', 'bonding', iface_name, 'arp-monitor', 'target'],
                value=ip_target,
                replace=False)


# configure bridge interafce from Network-Config version 2
def config_net_v2_bridge(config, iface_name: str, iface_config: dict) -> None:
    # find an usable bridge interface name
    iface_name = _find_usable_iface_name(config, 'bridge', 'br', iface_name)
    config_net_v2_common(config, 'bridge', iface_name, iface_config)
    # add an interface
    config.set(['interfaces', 'bridge', iface_name])
    config.set_tag(['interfaces', 'bridge'])
    # configure members
    for member in iface_config.get('interfaces', []):
        config.set([
            'interfaces', 'bridge', iface_name, 'member', 'interface', member
        ],
                   value=None,
                   replace=False)
        config.set_tag(
            ['interfaces', 'bridge', iface_name, 'member', 'interface'])
    # read bridge parameters that VyOS supports
    ageing_time = get_cfg_by_path(iface_config, 'parameters/ageing-time')
    priority = get_cfg_by_path(iface_config, 'parameters/priority')
    forward_delay = get_cfg_by_path(iface_config, 'parameters/forward-delay')
    hello_time = get_cfg_by_path(iface_config, 'parameters/hello-time')
    max_age = get_cfg_by_path(iface_config, 'parameters/max-age')
    stp = get_cfg_by_path(iface_config, 'parameters/stp')
    # apply parameters
    if ageing_time:
        config.set(['interfaces', 'bridge', iface_name, 'aging'],
                   value=ageing_time,
                   replace=True)
    if priority:
        config.set(['interfaces', 'bridge', iface_name, 'priority'],
                   value=priority,
                   replace=True)
    if forward_delay:
        config.set(['interfaces', 'bridge', iface_name, 'forwarding-delay'],
                   value=forward_delay,
                   replace=True)
    if hello_time:
        config.set(['interfaces', 'bridge', iface_name, 'hello-time'],
                   value=hello_time,
                   replace=True)
    if max_age:
        config.set(['interfaces', 'bridge', iface_name, 'max-age'],
                   value=max_age,
                   replace=True)
    if stp and stp is True:
        config.set(['interfaces', 'bridge', iface_name, 'stp'],
                   value=None,
                   replace=True)


# configure vlan interafce from Network-Config version 2
def config_net_v2_vlan(config, iface_name: str, iface_config: dict) -> None:
    logger.debug("Configuring VLAN interface {}".format(iface_name))
    # get mandatory interface parameters
    vlan_link = iface_config['link']
    vlan_id = iface_config['id']
    # prepare translation table for parent interface type
    interface_type_detect = {
        'eth': 'ethernet',
        'br': 'bridge',
        'bond': 'bonding'
    }
    # find interface type
    iface_type = interface_type_detect[vlan_link.rstrip('1234567890')]
    # create an interface
    config.set(['interfaces', iface_type, vlan_link, 'vif', vlan_id])
    config.set_tag(['interfaces', iface_type])
    config.set_tag(['interfaces', iface_type, vlan_link, 'vif'])
    # configure common parameters
    config_net_v2_common(config, iface_type, vlan_link, iface_config, vlan_id)


# configure ethernet interafce from Network-Config version 2
def config_net_v2_ethernet(config, iface_name: str,
                           iface_config: dict) -> None:
    config_net_v2_common(config, 'ethernet', iface_name, iface_config)

    # configure MAC
    if 'match' in iface_config and 'macaddress' in iface_config['match']:
        logger.debug("Setting MAC for {}: {}".format(
            iface_name, iface_config['match']['macaddress']))
        config.set(['interfaces', 'ethernet', iface_name, 'hw-id'],
                   value=iface_config['match']['macaddress'],
                   replace=True)
        config.set_tag(['interfaces', 'ethernet'])


# configure interface from networking config version 2
def set_config_interfaces_v2(config, netcfg: dict) -> None:
    logger.debug(
        "Configuring network using Cloud-init networking config version 2")
    for iface_name, iface_config in netcfg.get('ethernets', {}).items():
        config_net_v2_ethernet(config, iface_name, iface_config)
    for iface_name, iface_config in netcfg.get('bonds', {}).items():
        config_net_v2_bond(config, iface_name, iface_config)
    for iface_name, iface_config in netcfg.get('bridges', {}).items():
        config_net_v2_bridge(config, iface_name, iface_config)
    for iface_name, iface_config in netcfg.get('vlans', {}).items():
        config_net_v2_vlan(config, iface_name, iface_config)


# configure SSH server service
def set_config_ssh(config):
    logger.debug("Configuring SSH service")
    config.set(['service', 'ssh'], replace=True)
    config.set(['service', 'ssh', 'port'], value='22', replace=True)
    config.set(['service', 'ssh', 'client-keepalive-interval'], value='180', replace=True)


# configure hostname
def set_config_hostname(config, hostname, fqdn):
    if hostname:
        logger.debug("Configuring hostname to: {}".format(hostname_filter(hostname)))
        config.set(['system', 'host-name'], value=hostname_filter(hostname), replace=True)
    if fqdn:
        try:
            domain_name = fqdn.partition("{}.".format(hostname))[2]
            if domain_name:
                logger.debug("Configuring domain-name to: {}".format(hostname_filter(domain_name)))
                config.set(['system', 'domain-name'], value=hostname_filter(domain_name), replace=True)
        except Exception as err:
            logger.error("Failed to configure domain-name: {}".format(err))


# main config handler
def handle(name, cfg, cloud, log, _args):
    logger.debug("Cloud-init config: {}".format(cfg))
    # fetch all required data from Cloud-init
    # Datasource name
    dsname = cloud.datasource.dsname
    logger.debug("Datasource: {}".format(dsname))
    # Metadata (datasource specific)
    metadata_ds = cloud.datasource.metadata
    logger.debug("Meta-Data ds: {}".format(metadata_ds))
    # Metadata in stable v1 format (the same structure for all datasources)
    instance_data_json = load_json(load_file("{}/{}".format(cloud.datasource.paths.run_dir, INSTANCE_JSON_FILE)))
    metadata_v1 = instance_data_json.get('v1')
    logger.debug("Meta-Data v1: {}".format(metadata_v1))
    # User-Data
    userdata = cloud.datasource.userdata
    logger.debug("User-Data: {}".format(userdata))
    # Vendor-Data
    vendordata = cloud.datasource.vendordata
    logger.debug("Vendor-Data: {}".format(vendordata))
    # Network-config
    netcfg = cloud.datasource.network_config
    if netcfg:
        netcfg_src = dsname
    else:
        init_stage = Init()
        (netcfg, netcfg_src) = init_stage._find_networking_config()
    # Depending on Network-config version (and maybe something else)
    # Cloud-init may provide output here in different formats. That
    # is why we need to add this additional validation and conversion
    # to what we expect to see in the end
    netcfg = netcfg.get('network', netcfg)
    logger.debug("Network-config: {}".format(netcfg))
    logger.debug("Network-config source: {}".format(netcfg_src))
    # Hostname with FQDN (if exist)
    hostname_info = get_hostname_fqdn(cfg, cloud, metadata_only=True)
    hostname = getattr(hostname_info, 'hostname', None)
    fqdn = getattr(hostname_info, 'fqdn', None)
    if hostname is None and isinstance(hostname_info, (tuple, list)) and len(hostname_info) >= 2:
        hostname, fqdn = hostname_info[0], hostname_info[1]
    logger.debug("Hostname: {}, FQDN: {}".format(hostname, fqdn))
    # Get users list
    (users, _) = ug_util.normalize_users_groups(cfg, cloud.distro)
    logger.debug("Users: {}".format(users))
    (default_user, default_user_config) = ug_util.extract_default(users)
    logger.debug("Default user: {}".format(default_user))
    # Get OVF properties
    ovf_environment = {}
    if 'OVF' in dsname:
        ovf_environment = ovf_get_properties(cloud.datasource.environment)
        logger.debug("OVF environment: {}".format(ovf_environment))

    # VyOS configuration file selection
    cfg_file_name = '/opt/vyatta/etc/config/config.boot'
    bak_file_name = '/usr/share/vyos/config.boot.default'

    # open configuration file
    if not Path(cfg_file_name).exists():
        file_name = bak_file_name
    else:
        file_name = cfg_file_name

    logger.debug("Using configuration file: {}".format(file_name))
    # We must run all migrations on the config before Cloud-init will modify it
    # Otherwise, regardless of proper syntax for the current version, migrations will be re-run with unpredictable result
    logger.debug("Running migrations for: {}".format(file_name))
    run(['/usr/libexec/vyos/run-config-migration.py', file_name])
    with open(file_name, 'r') as f:
        config_file = f.read()
    config = ConfigTree(config_file)

    # Initialization of variables
    DEFAULT_VYOS_USER = 'vyos'
    DEFAULT_VYOS_PASSWORD = 'vyos'
    logins_configured = False
    network_configured = False

    # configure system logins
    # Prepare SSH public keys for default user, to be sure that global keys applied to the default account (if it exist)
    # If the ssh key is left emty on an OVA deploy the OVF datastore passes an empty string which generates an invalid key error.
    # Set the ssh_keys variable from the metadata_v1['public_ssh_keys'] checked for empty strings.
    ssh_keys = [key for key in metadata_v1['public_ssh_keys'] if key]
    # append SSH keys from cloud-config
    ssh_keys.extend(cfg.get('ssh_authorized_keys', []))
    # Configure authentication for default user account
    if default_user:
        # key-based
        for ssh_key in ssh_keys:
            if set_ssh_login(config, default_user, ssh_key):
                logins_configured = True
        # password-based
        password = cfg.get('password')
        if password:
            if set_pass_login(config, default_user, password):
                logins_configured = True

    # Configure all users accounts
    for user, user_cfg in users.items():
        # Configure password-based authentication
        password = user_cfg.get('passwd')
        if password and password != '':
            if set_pass_login(config, user, password):
                logins_configured = True

        # Configure key-based authentication
        for ssh_key in user_cfg.get('ssh_authorized_keys', []):
            if set_ssh_login(config, user, ssh_key):
                logins_configured = True

    # Create a fallback user if there was no others
    if not logins_configured:
        logger.debug("Adding fallback user: {}".format(DEFAULT_VYOS_USER))
        set_pass_login(config, DEFAULT_VYOS_USER, DEFAULT_VYOS_PASSWORD)

    # apply settings from OVF template
    if 'OVF' in dsname:
        set_config_ovf(config, ovf_environment)
        # Empty hostname option may be interpreted as 'null' string by some hypervisors
        # we need to replace it to the empty value to process it later properly
        if hostname and hostname == 'null':
            hostname = None
        network_configured = True

    # get network-config control options
    network_config_global: str = get_cfg_by_path(cfg, 'network/config', '')
    network_config_vyos: str = get_cfg_by_path(
        cfg, 'vyos_config_options/network_config', network_config_global)
    if network_config_vyos == 'disabled':
        logger.debug("Network-config is disabled (global/vyos): {}/{}".format(
            network_config_global, network_config_vyos))

    # process networking configuration data
    if netcfg and network_configured is False and network_config_vyos != 'disabled':
        # check which one version of config we have
        # version 1
        if netcfg['version'] == 1:
            for interface_config in netcfg['config']:
                set_config_interfaces_v1(config, interface_config)
            network_configured = True

        # version 2
        if netcfg['version'] == 2:
            set_config_interfaces_v2(config, netcfg)
            network_configured = True

    # enable DHCPv4 on eth0 if network still not configured
    if network_configured is False:
        logger.debug("Configuring DHCPv4 on eth0 interface (fallback)")
        set_ipaddress(config, 'ethernet', 'eth0', 'dhcp')
        # this will protect from unsupported MTU values
        set_ether_mtu(config, 'eth0', DEFAULT_ETH_MTU)

    # enable SSH service
    set_config_ssh(config)
    # configure hostname and domain
    if hostname:
        set_config_hostname(config, hostname, fqdn)
    else:
        set_config_hostname(config, 'vyos', None)

    # save a new configuration file
    try:
        with open(cfg_file_name, 'w') as f:
            f.write(config.to_string())
            logger.debug("Configuration file saved: {}".format(cfg_file_name))
    except Exception as e:
        logger.error("Failed to write configs into file {}: {}".format(cfg_file_name, e))
