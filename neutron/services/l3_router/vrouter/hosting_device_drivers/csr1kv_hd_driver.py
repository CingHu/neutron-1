# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# @author: Bob Melander, Cisco Systems, Inc.

import netaddr

from oslo.config import cfg

from neutron import manager
from neutron.openstack.common import log as logging
from neutorn.services.l3_routers.vrouter import driver_api


LOG = logging.getLogger(__name__)


# Length mgmt port UUID to be part of VM's config drive filename
CFG_DRIVE_UUID_START = 24
CFG_DRIVE_UUID_LEN = 12

CSR1KV_HD_DRIVER_OPTS = [
    cfg.StrOpt('csr1kv_configdrive_template', default='csr1kv_cfg_template',
               help=_("CSR1kv configdrive template file.")),
    cfg.IntOpt('csr1kv_booting_time', default=420,
               help=_('Booting time in seconds before a CSR1kv '
                      'becomes operational.')),
    cfg.StrOpt('csr1kv_username', default='stack',
               help=_('Username to use for CSR1kv configurations.')),
    cfg.StrOpt('csr1kv_password', default='cisco',
               help=_('Password to use for CSR1kv configurations.')),
]

cfg.CONF.register_opts(CSR1KV_HD_DRIVER_OPTS)


class CSR1kvHostingDeviceDriver(driver_api.HostingDeviceConfigDriver):

    @property
    def _core_plugin(self):
        return manager.NeutronManager.get_plugin()

    def hosting_device_name(self):
        return "CSR1kv"

    def create_config(self, context, mgmtport):
        mgmt_ip = mgmtport['fixed_ips'][0]['ip_address']
        subnet_data = self._core_plugin.get_subnet(
            context, mgmtport['fixed_ips'][0]['subnet_id'],
            ['cidr', 'gateway_ip', 'dns_nameservers'])
        netmask = str(netaddr.IPNetwork(subnet_data['cidr']).netmask)
        params = {'<ip>': mgmt_ip, '<mask>': netmask,
                  '<gw>': subnet_data['gateway_ip'],
                  '<name_server>': '8.8.8.8'}
        try:
            cfg_template_filename = (cfg.CONF.templates_path + "/" +
                                     cfg.CONF.csr1kv_configdrive_template)
            cfg_data = ''
            with open(cfg_template_filename, 'r') as cfg_template_file:
                # insert proper instance values in the template
                for line in cfg_template_file:
                    tokens = line.strip('\n').split(' ')
                    line = ' '.join(map(lambda x: params.get(x, x),
                                        tokens)) + '\n'
                    cfg_data += line
            return {'iosxe_config.txt': cfg_data}
        except IOError as e:
            LOG.error(_('Failed to create config file: %s. Trying to'
                        'clean up.'), str(e))
            raise

    def get_device_info_for_agent(self, hosting_device):
        """Returns information about <hosting_device> needed by config agent.

            Convenience function that service plugins can use to populate
            their resources with information about the device hosting their
            logical resource.
        """
        credentials = {'username': cfg.CONF.hosting_devices.csr1kv_username,
                       'password': cfg.CONF.hosting_devices.csr1kv_password}
        mgmt_ip = (hosting_device.management_port['fixed_ips'][0]['ip_address']
                   if hosting_device.management_port else None)
        return {'id': hosting_device.id,
                'credentials': credentials,
                'management_ip_address': mgmt_ip,
                'protocol_port': hosting_device.protocol_port,
                'created_at': str(hosting_device.created_at),
                'booting_time': cfg.CONF.hosting_devices.csr1kv_booting_time,
                'cfg_agent_id': hosting_device.cfg_agent_id}
